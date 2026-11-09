"""Private File Transfer Assistant channel, isolated from friend/group takeover."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from host_runtime import lock_file
from native_controls import atomic, control_text
from native_backend import NativeConnection, key as binding_key
from native_ai_context import context_for
from ai_reply import generate, protect

PREFIX='【个人助手】'


def eligible_event(event):
    data=event.get('data',{})
    # API-generated sends (including our own responses and status feedback) never
    # become owner requests. Ordinary personal requests come from WeChat sync.
    return (event.get('kind')=='message.committed' and data.get('origin') in ('live','catchup')
            and data.get('direction')=='outgoing' and data.get('threadId')=='filehelper'
            and isinstance(data.get('messageId'),str))


def manual_api_text(event,row,account):
    data=event.get('data',{})
    text=row.get('body') or ''
    return (data.get('origin')=='local_send' and data.get('threadId')=='filehelper'
            and row.get('threadId')=='filehelper' and row.get('direction')=='outgoing'
            and row.get('accountId')==account and row.get('type')==1 and bool(text)
            and not text.startswith((PREFIX,'AI 自动回复状态\n')))


def load_config(root):
    return json.loads((Path(root)/'private-data/workdesk-native-ai.json').read_text(encoding='utf-8'))


def enabled(root,epoch):
    try:
        c=load_config(root)
        return c.get('ownerAssistant') is True and str(c.get('ownerEpoch',''))==epoch
    except (OSError,ValueError):return False


def draft(root,config,ids,history,since=0):
    if not enabled(root,str(config.get('ownerEpoch',''))):return {'state':'skipped'}
    connection=NativeConnection({'directory':str(root),'account':config['account']})
    try:
        rows=[]
        for ident in ids:
            row=connection.request('messages/'+__import__('urllib.parse',fromlist=['quote']).quote(ident,safe=''))
            if (row.get('direction')!='outgoing' or row.get('threadId')!='filehelper'
                    or row.get('accountId')!=config['account']):raise ValueError('Owner message identity mismatch')
            try:stamp=datetime.fromisoformat(row.get('createdAt','').replace('Z','+00:00')).timestamp()
            except (ValueError,TypeError):stamp=0
            if stamp<since:continue
            if row.get('type')==1 and (control_text(row.get('body')) or not row.get('body')
                                      or row['body'].startswith((PREFIX,'AI 自动回复状态\n'))):continue
            if row.get('type') not in (1,3,34,43,49):continue
            rows.append({**row,'direction':'incoming'})
        if not rows:return {'state':'skipped'}
        records=context_for(rows,rows,root,connection.base,connection.request,
                            video_enabled=config.get('videoAnalysis',False),voice_enabled=config.get('voiceReplies',False),voice_language=config.get('voiceLanguage','zh'))
        if not enabled(root,str(config.get('ownerEpoch',''))):return {'state':'skipped'}
        if len(rows)==1 and rows[0].get('type')==34 and len(records)==1:
            text=records[0].get('text','')
            if text.startswith('语音自动转写'):
                utterance=text.split('：',1)[-1].split('\n',1)[0].strip()
                action=control_text(utterance)
                if action in ('pause','start','status'):
                    if not enabled(root,str(config.get('ownerEpoch',''))):return {'state':'skipped'}
                    from native_backend import NativeAI
                    ai=NativeAI({'directory':str(root),'account':config['account']},None)
                    if action=='status':
                        from native_controls import OwnerControls
                        response=OwnerControls(root).status_text()
                    else:
                        try:response=(ai.pause() if action=='pause' else ai.start())['status']
                        except Exception:response='旧回复任务尚未安全退出，暂未完成开启，请稍后再试。'
                    return {'state':'prepared','text':PREFIX+' 按语音转写“'+utterance+'”处理：\n'+response,
                            'images':[],'requestSummary':text}
        c=dict(config);c['ownerConversation']=True
        c['apiKey']=protect(c.pop('encryptedKey'),decrypt=True) if c.get('encryptedKey') else ''
        result=generate(c,(history+records)[-12:])
        summary='\n'.join(r.get('text') or '[主人发送了%s，内容见上一轮分析]'%r['kind'] for r in records)[:4000]
        return {'state':'prepared','text':PREFIX+' '+str(result),'images':list(getattr(result,'images',())),
                'requestSummary':summary}
    finally:connection.close()


def deliver(root,account,task):
    if not enabled(root,task['epoch']):return {'state':'cancelled'}
    connection=NativeConnection({'directory':str(root),'account':account})
    try:
        connection.selected='filehelper';connection.known['filehelper']={'id':'filehelper','kind':'direct'}
        if task.get('images'):
            from native_images import send_image
            image=send_image(connection,binding_key('filehelper'),task['images'][0],
                request_id=task['key']+'-image',should_stop=lambda:not enabled(root,task['epoch']))
            if image.get('state')!='observed':return {'state':'uncertain','detail':'图片发送结果需要核对。'}
        if not enabled(root,task['epoch']):return {'state':'cancelled'}
        text=task['text'];body=text[len(PREFIX):].lstrip() if text.startswith(PREFIX) else text
        chunks=[body[i:i+3300] for i in range(0,len(body),3300)] or ['']
        for index,chunk in enumerate(chunks):
            if not enabled(root,task['epoch']):return {'state':'cancelled'}
            label=PREFIX+(' (%s/%s)'%(index+1,len(chunks)) if len(chunks)>1 else '')+' '
            result=connection.request('sends',{'threadId':'filehelper','text':label+chunk},task['key']+'-text-'+str(index))
            until=time.monotonic()+30
            while result.get('state') in ('queued','running','preparing','uploading','submitting') and time.monotonic()<until:
                time.sleep(.2)
                result=connection.request('sends/'+__import__('urllib.parse',fromlist=['quote']).quote(result['id'],safe=''))
            if result.get('state')!='accepted' or not result.get('serverId'):return {'state':'uncertain'}
        return {'state':'accepted'}
    except Exception:return {'state':'uncertain','detail':'发送结果需要核对，未自动重发。'}
    finally:connection.close()


def main(root):
    root=Path(root);private=root/'private-data';path=private/'owner-assistant-state.json';status_path=private/'owner-assistant-status.json'
    with (private/'owner-assistant.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):lock.write(b'0');lock.flush()
        lock.seek(0)
        try:lock_file(lock)
        except OSError:return
        config=load_config(root)
        connection=NativeConnection({'directory':str(root),'account':config['account']})
        atomic(status_path,{'pid':os.getpid(),'state':'starting','updatedAt':time.time()})
        try:
            state=json.loads(path.read_text()) if path.exists() else {}
            if state.get('account')!=config['account'] or 'cursor' not in state:
                state={'account':config['account'],'cursor':str(config.get('ownerStartCursor') or connection.request('threads?limit=1')['asOfEventCursor']),
                       'queue':[],'history':[],'task':None,'replies':0,'activatedAt':int(config.get('ownerSince') or time.time()),
                       'epoch':str(config.get('ownerEpoch',''))}
            if state.get('task',{} ) and state['task'].get('phase')=='sending':
                state['blocked']='上次发送在进程退出时尚未确认，请在文件传输助手核对，未自动重发。'
                state['task']=None
            task=state.get('task')
            if task and task.get('phase')=='generating':state['queue']=task['ids']+state['queue'];state['task']=None
            atomic(path,state)
            future=None;phase=None
            with ThreadPoolExecutor(max_workers=1) as pool:
                while True:
                    config=load_config(root);epoch=str(config.get('ownerEpoch',''))
                    on=config.get('ownerAssistant') is True
                    try:
                        if state.get('epoch')!=epoch:
                            state['queue']=[];state['epoch']=epoch
                            state['activatedAt']=int(config.get('ownerSince') or time.time())
                            if config.get('ownerStartCursor'):state['cursor']=str(config['ownerStartCursor'])
                            if future is None:state['task']=None
                            atomic(path,state)
                        reviewed=private/'owner-assistant-reviewed'
                        if reviewed.exists() and future is None:
                            state.pop('blocked',None);state['queue']=[];state['task']=None
                            state['cursor']=str(connection.request('threads?limit=1')['asOfEventCursor'])
                            atomic(path,state);reviewed.unlink(missing_ok=True)
                        if future is not None and future.done():
                            try:result=future.result()
                            except Exception:result={'state':'error'}
                            task=state['task'];future=None
                            if not enabled(root,task['epoch']):state['task']=None
                            elif phase=='draft':
                                if result['state']=='prepared':state['task']={**task,**result,'phase':'prepared'}
                                elif result['state']=='skipped':state['task']=None
                                else:state['task']={**task,'phase':'prepared','text':PREFIX+' 这次请求处理失败，请稍后重试；没有声称已完成操作。','images':[],'requestSummary':'[处理失败]'}
                            else:
                                if result['state']=='accepted':
                                    task=state['task'];state['replies']+=1
                                    state['history']=(state['history']+[
                                        {'kind':'text','direction':'incoming','text':task.get('requestSummary','')},
                                        {'kind':'text','direction':'outgoing','text':task['text'][len(PREFIX):].strip()}])[-12:]
                                elif result['state']=='uncertain':state['blocked']=result.get('detail','发送结果未知，请核对。')
                                state['task']=None
                            atomic(path,state)
                        if not on:
                            state['queue']=[]
                            if future is None:state['task']=None;atomic(path,state);break
                        if on:
                            events=connection.request('events?after='+str(state['cursor'])+'&limit=200')
                            for event in events.get('items',[]):
                                allowed=eligible_event(event)
                                data=event.get('data',{})
                                if (not allowed and event.get('kind')=='message.committed' and data.get('origin')=='local_send'
                                        and data.get('threadId')=='filehelper' and data.get('messageId')):
                                    row=connection.request('messages/'+__import__('urllib.parse',fromlist=['quote']).quote(data['messageId'],safe=''))
                                    allowed=manual_api_text(event,row,config['account'])
                                if allowed:
                                    ident=event['data']['messageId']
                                    active=state.get('task',{} ) or {}
                                    if ident not in state['queue'] and ident not in active.get('ids',[]):state['queue'].append(ident)
                                state['cursor']=str(event['cursor'])
                            if events.get('items'):atomic(path,state)
                        if on and future is None and not state.get('blocked'):
                            if state.get('task') and state['task']['phase']=='prepared':
                                if enabled(root,state['task']['epoch']):
                                    state['task']['phase']='sending';atomic(path,state)
                                    future=pool.submit(deliver,root,config['account'],dict(state['task']));phase='send'
                                else:state['task']=None;atomic(path,state)
                            elif state['queue']:
                                ids=state['queue'][:6];state['queue']=state['queue'][6:]
                                task={'ids':ids,'epoch':epoch,'phase':'generating',
                                      'key':'owner-dialog-'+hashlib.sha256((config['account']+'|'.join(ids)).encode()).hexdigest()[:40]}
                                state['task']=task;atomic(path,state)
                                future=pool.submit(draft,root,dict(config),ids,list(state['history']),
                                                   max(state['activatedAt'],int(config.get('ownerSince',0))));phase='draft'
                        atomic(status_path,{'pid':os.getpid(),'state':'stopping' if not on else 'blocked' if state.get('blocked') else 'working' if future else 'listening',
                            'updatedAt':time.time(),'replies':state['replies'],'queued':len(state['queue']),'detail':state.get('blocked','')})
                    except Exception as error:
                        atomic(status_path,{'pid':os.getpid(),'state':'retrying','updatedAt':time.time(),'errorType':type(error).__name__})
                    time.sleep(.5)
            atomic(status_path,{'pid':os.getpid(),'state':'stopped','updatedAt':time.time(),'replies':state['replies']})
        finally:connection.close()


if __name__=='__main__':main(sys.argv[1])
