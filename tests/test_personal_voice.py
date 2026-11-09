import json
from pathlib import Path
import tempfile
import threading
import time
from datetime import datetime,timezone
from unittest.mock import Mock,patch
import unittest
import native_owner
from native_owner import eligible_event,manual_api_text,deliver,PREFIX
from native_voice import fetch_voice,transcribe
from native_ai_context import context_for,replyable
from ai_reply import generate, ReplyError, AutoReply


class PersonalVoiceTests(unittest.TestCase):
    def event(self,direction='outgoing',origin='live',thread='filehelper'):
        return {'kind':'message.committed','data':{'direction':direction,'origin':origin,'threadId':thread,'messageId':'m'}}

    def test_only_own_filehelper_sync_is_a_personal_request(self):
        self.assertTrue(eligible_event(self.event()))
        for e in [self.event('incoming'),self.event(thread='group'),self.event(origin='local_send')]:
            self.assertFalse(eligible_event(e))

    def test_manual_web_text_is_allowed_but_generated_feedback_is_not(self):
        row={'type':1,'body':'帮我查天气','accountId':'owner','threadId':'filehelper','direction':'outgoing'}
        e=self.event(origin='local_send')
        self.assertTrue(manual_api_text(e,row,'owner'))
        for body in [PREFIX+' 你好','AI 自动回复状态\n已开启']:
            self.assertFalse(manual_api_text(e,{**row,'body':body},'owner'))
        self.assertFalse(manual_api_text(e,{**row,'accountId':'other'},'owner'))

    def test_global_pause_does_not_disable_personal_channel_but_epoch_change_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'private-data';p.mkdir();(p/'global.stop').touch()
            config=p/'workdesk-native-ai.json';config.write_text(json.dumps({'ownerAssistant':True,'ownerEpoch':'new'}))
            self.assertTrue(native_owner.enabled(tmp,'new'))
            with patch('native_owner.NativeConnection') as connection:
                self.assertEqual(deliver(tmp,'owner',{'epoch':'old'})['state'],'cancelled')
            connection.assert_not_called()

    def test_long_responses_are_split_with_prefixes_and_stable_unique_keys(self):
        c=Mock(known={});c.request.return_value={'state':'accepted','serverId':'confirmed'}
        with patch('native_owner.enabled',return_value=True),patch('native_owner.NativeConnection',return_value=c):
            result=deliver('/unused','owner',{'epoch':'e','key':'stable','text':PREFIX+' '+('甲'*7000)})
        self.assertEqual(result['state'],'accepted');self.assertEqual(c.request.call_count,3)
        for call in c.request.call_args_list:
            self.assertTrue(call.args[1]['text'].startswith(PREFIX));self.assertLess(len(call.args[1]['text']),3500)
        self.assertEqual(len({call.args[2] for call in c.request.call_args_list}),3)

    def test_voice_incoming_can_be_transcribed_but_off_switch_prevents_download(self):
        row={'type':34,'direction':'incoming','id':'v','createdAt':'2026-01-01','threadId':'friend'}
        self.assertTrue(replyable(row))
        with patch('native_ai_context.Previews'),patch('native_ai_context.fetch_voice') as speech:
            value=context_for([row],[row],None,None,None,voice_enabled=False)
        speech.assert_not_called();self.assertIn('尚未开启',value[0]['text'])
        with patch('native_ai_context.Previews'),patch('native_ai_context.fetch_voice',return_value='本地转写：你好'):
            value=context_for([row],[row],None,None,None,voice_enabled=True)
        self.assertIn('你好',value[0]['text'])

    def test_voice_canonical_thread_and_integrity_are_checked(self):
        c=Mock();c.request.return_value={'type':34,'threadId':'other'}
        with patch('native_voice.binary') as download:
            with self.assertRaises(ValueError):fetch_voice(c,{'id':'v','threadId':'friend'})
        download.assert_not_called()
        c.request.side_effect=[{'type':34,'threadId':'friend'}, {'items':[{'id':'a','kind':'voice','variant':'normal','state':'available','contentType':'audio/wav','byteLength':3,'sha256':'bad'}]}]
        with patch('native_voice.binary',return_value=b'abc'),patch('native_voice.transcribe') as recognize:
            with self.assertRaisesRegex(ValueError,'完整性'):fetch_voice(c,{'id':'v','threadId':'friend'})
        recognize.assert_not_called()

    def test_empty_voice_is_not_invented(self):
        with self.assertRaises(ValueError):transcribe(b'')

    def test_canonical_owner_identity_is_rechecked_before_model_use(self):
        c=Mock();c.request.return_value={'direction':'incoming','accountId':'other','threadId':'filehelper'}
        with patch('native_owner.enabled',return_value=True),patch('native_owner.NativeConnection',return_value=c),patch('native_owner.generate') as model:
            with self.assertRaises(ValueError):native_owner.draft('/unused',{'account':'owner','ownerEpoch':'e'},['m'],[])
        model.assert_not_called()

    def test_personal_dialogue_has_its_own_prompt_and_longer_output_budget(self):
        config={'ownerConversation':True,'style':'自然','webSearch':True}
        with patch('ai_web.generate_with_search',return_value='文'*1000) as model:
            self.assertEqual(len(generate(config,[{'kind':'text','direction':'incoming','text':'详细解释'}])),1000)
        self.assertIn('个人助手',model.call_args.args[1][0]['content'])
        with patch('ai_web.generate_with_search',return_value='文'*1000):
            with self.assertRaises(ReplyError):generate({**config,'ownerConversation':False},[])

    def test_uncertain_image_does_not_send_caption_or_retry(self):
        c=Mock(known={})
        with patch('native_owner.enabled',return_value=True),patch('native_owner.NativeConnection',return_value=c), \
             patch('native_images.send_image',return_value={'state':'unknown'}):
            result=deliver('/unused','owner',{'epoch':'e','key':'k','text':'图片好了','images':['synthetic']})
        self.assertEqual(result['state'],'uncertain');c.request.assert_not_called()

    def test_private_event_loop_replies_once_while_global_ai_is_paused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);private=root/'private-data';private.mkdir();(private/'global.stop').touch()
            config=dict(account='owner',ownerAssistant=True,ownerEpoch='e',encryptedKey='',style='自然',webSearch=False,mediaReplies=False)
            config_path=private/'workdesk-native-ai.json';config_path.write_text(json.dumps(config))
            stamp=datetime.now(timezone.utc).isoformat()
            rows={'user':dict(id='user',threadId='filehelper',accountId='owner',direction='outgoing',type=1,body='你好',createdAt=stamp)}
            events=[dict(cursor='2',kind='message.committed',data=dict(direction='outgoing',origin='live',threadId='filehelper',messageId='user'))]
            sent=[];quiet=[0]
            class Connection:
                base='http://localhost/';root=Path(tmp)
                def __init__(self,*a,**k):self.known={}
                def close(self):pass
                def request(self,path,data=None,key=None):
                    if path.startswith('threads?'):return {'asOfEventCursor':'1'}
                    if path.startswith('messages/'):return rows[path.split('/',1)[1]]
                    if path.startswith('events?'):
                        after=int(path.split('after=')[1].split('&')[0])
                        answer=[e for e in events if int(e['cursor'])>after]
                        if sent and not answer:
                            quiet[0]+=1
                            if quiet[0]>=3:config_path.write_text(json.dumps({**config,'ownerAssistant':False,'ownerEpoch':'off'}))
                        return {'items':answer}
                    if path=='sends':
                        sent.append((data,key));rows['assistant']=dict(rows['user'],id='assistant',body=data['text'])
                        events.append(dict(cursor='3',kind='message.committed',data=dict(direction='outgoing',origin='local_send',threadId='filehelper',messageId='assistant')))
                        return {'state':'accepted','serverId':'confirmed'}
                    raise AssertionError(path)
            original_sleep=time.sleep
            with patch('native_owner.NativeConnection',Connection),patch('native_owner.generate',return_value='你好，需要帮你做什么？'),patch('native_owner.time.sleep',side_effect=lambda _:original_sleep(.01)):
                worker=threading.Thread(target=native_owner.main,args=(root,),daemon=True);worker.start();worker.join(5)
                if worker.is_alive():
                    config_path.write_text(json.dumps({**config,'ownerAssistant':False}));worker.join(2)
                self.assertFalse(worker.is_alive())
            self.assertEqual(len(sent),1)
            self.assertTrue(sent[0][0]['text'].startswith(PREFIX))
            state=json.loads((private/'owner-assistant-state.json').read_text(encoding='utf-8'))
            self.assertEqual(state['replies'],1)
