"""Durable text draft review. No module operation sends a message."""
import json
from pathlib import Path
import time
from config_store import edit_config


def path(root):return Path(root)/'private-data/reply-review.json'


def enqueue(root, account, thread, key, text):
    with edit_config(path(root)) as records:
        records.setdefault(key,{'account':account,'thread':thread,'text':text,'state':'pending','createdAt':time.time()})
    return {'state':'pending_review'}


def pending(root):
    try:records=json.loads(path(root).read_text(encoding='utf-8'))
    except (OSError,ValueError):return []
    return [{'key':k,**v} for k,v in records.items() if v.get('state') in ('pending','approved','sending','unknown') and time.time()-v.get('createdAt',0)<86400]


def decide(root,key,approved):
    with edit_config(path(root)) as records:
        item=records.get(key)
        if not item or item.get('state')!='pending':raise ValueError('草稿已处理或不存在，请刷新。')
        if time.time()-item['createdAt']>=86400:raise ValueError('草稿已过期，不再发送。')
        item['state']='approved' if approved else 'rejected'
    return '已批准，等待后台发送确认。' if approved else '已丢弃草稿。'


def edit(root,key,text):
    if not isinstance(text,str) or not text.strip() or len(text)>3000:
        raise ValueError('草稿必须为 1–3000 字。')
    from native_controls import control_text
    if control_text(text):raise ValueError('草稿不能冒充助手控制口令。')
    with edit_config(path(root)) as records:
        item=records.get(key)
        if not item or item.get('state')!='pending':raise ValueError('只能编辑待审核草稿。')
        item['text']=text.strip()


def claim(root,account):
    with edit_config(path(root)) as records:
        for key,item in records.items():
            if item.get('state')=='approved' and item.get('account')==account and time.time()-item['createdAt']<86400:
                item['state']='sending'
                return {'key':key,**item}
    return None


def finish(root,key,state):
    with edit_config(path(root)) as records:records[key]['state']=state
