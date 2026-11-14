"""Explicit, bounded provider checks; never save or echo API credentials."""
import json
import time
import urllib.error
import urllib.request
from ai_reply import endpoint, protect, NoRedirect, ReplyError


def settings(data, saved=None):
    saved=saved or {}
    key=data.get('apiKey','')
    if not isinstance(key,str) or len(key)>4096 or '\n' in key or '\r' in key:
        raise ValueError('API 密钥格式无效。')
    if not key and saved.get('encryptedKey'):
        key=protect(saved['encryptedKey'],decrypt=True)
    try:url=endpoint(data.get('endpoint','').strip())
    except ReplyError as error:raise ValueError(str(error)) from None
    return dict(endpoint=url,apiKey=key,model=data.get('model','').strip())


def request(config, url, data=None):
    headers={'Content-Type':'application/json','User-Agent':'Workdesk/diagnostics'}
    if config['apiKey']:headers['Authorization']='Bearer '+config['apiKey']
    req=urllib.request.Request(url,headers=headers,data=None if data is None else json.dumps(data).encode())
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=config.get('requestTimeout',30)) as response:raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('接口响应过大，已停止测试。')
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        messages={401:'密钥无效或已过期，请检查 API Key。',403:'服务拒绝访问，请检查密钥权限或服务限制。',
                  404:'接口地址或模型不存在，请检查 URL 和模型 ID。',429:'请求受限，可能额度不足或触发限流，请检查服务账号。'}
        raise ValueError(messages.get(error.code,'接口返回 HTTP %s，请稍后重试。'%error.code)) from None
    except (TimeoutError,urllib.error.URLError,OSError) as error:
        if isinstance(error,TimeoutError) or isinstance(getattr(error,'reason',None),TimeoutError):
            raise ValueError('API 等待响应超时（%s 秒），可能是模型处理较慢。'%config.get('requestTimeout',30)) from None
        raise ValueError('无法连接 API，请检查 URL、网络和代理设置。') from None
    except (json.JSONDecodeError,UnicodeError):
        raise ValueError('接口未返回兼容的 JSON，可能填入了网页地址。') from None
    except ReplyError:
        raise ValueError('接口发生重定向，请使用最终 API 地址后重试。') from None


def list_models(data, saved=None):
    config=settings(data,saved)
    value=request(config,config['endpoint'][:-len('/chat/completions')]+'/models')
    if not isinstance(value,dict) or not isinstance(value.get('data'),list):
        raise ValueError('此服务未提供兼容的模型列表，请手动填写模型 ID。')
    ids=sorted({row['id'] for row in value['data'] if isinstance(row,dict) and isinstance(row.get('id'),str)
                and row['id'] and len(row['id'])<=120 and not any(ord(c)<32 for c in row['id'])})[:1000]
    if not ids:raise ValueError('服务未返回可选模型，请向服务提供方确认模型 ID。')
    return ids


def test_chat(data,saved=None):
    config=settings(data,saved)
    if not config['model']:raise ValueError('请先填写或获取并选择模型 ID。')
    start=time.monotonic()
    result=request(config,config['endpoint'],dict(model=config['model'],messages=[{'role':'user','content':'Reply only OK.'}],
                                                max_tokens=48,stream=False))
    try:text=result['choices'][0]['message']['content']
    except (TypeError,KeyError,IndexError):raise ValueError('接口没有返回有效对话内容，请确认支持 Chat Completions。') from None
    if not isinstance(text,str) or not text.strip():raise ValueError('接口已响应，但没有返回文字，暂未确认模型可用。')
    return '对话测试成功 · %.1f 秒。此结果仅确认当前模型文字对话可用，联网/图片能力需另行支持。'%(time.monotonic()-start)
