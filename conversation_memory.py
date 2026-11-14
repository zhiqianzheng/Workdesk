"""Local episodic memory with normalized character-ngram vectors and cosine recall.
No remote embedding service or inferred personal facts are required.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from contextlib import contextmanager


def vector(text):
    text=re.sub(r'\s+','',text.casefold())
    result={}
    for size in (2,3):
        for i in range(max(0,len(text)-size+1)):
            token=text[i:i+size]
            key=str(int.from_bytes(hashlib.blake2b(token.encode(),digest_size=4).digest(),'big')%8192)
            result[key]=result.get(key,0)+1
    norm=math.sqrt(sum(v*v for v in result.values())) or 1
    return {k:v/norm for k,v in result.items()}


@contextmanager
def connect(root):
    folder=Path(root)/'private-data';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'conversation-memory.sqlite3'
    db=sqlite3.connect(path,timeout=5)
    path.chmod(0o600)
    db.execute('PRAGMA busy_timeout=5000')
    db.execute('CREATE TABLE IF NOT EXISTS memories (account TEXT,thread TEXT,message TEXT,sender TEXT,body TEXT,stamp TEXT,learned REAL,embedding TEXT,PRIMARY KEY(account,thread,message))')
    db.execute('CREATE TABLE IF NOT EXISTS settings (account TEXT,thread TEXT,enabled INTEGER,since REAL,PRIMARY KEY(account,thread))')
    db.execute('CREATE TABLE IF NOT EXISTS forgotten (account TEXT,thread TEXT,message TEXT,PRIMARY KEY(account,thread,message))')
    db.commit()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback();raise
    finally:
        db.close()


def semantic_vectors(root,texts):
    config=json.loads((Path(root)/'private-data/workdesk-native-ai.json').read_text(encoding='utf-8'))
    model=config.get('memoryEmbeddingModel','').strip()
    if not model:return None
    from api_diagnostics import request, settings
    data=settings({'endpoint':config['endpoint'],'model':model},config)
    url=data['endpoint'][:-len('/chat/completions')]+'/embeddings'
    response=request(data,url,{'model':model,'input':texts})
    values=sorted(response.get('data',[]),key=lambda x:x.get('index',0))
    if len(values)!=len(texts):raise ValueError('Embedding响应数量不符。')
    result=[]
    for row in values:
        embedding=row.get('embedding',[])
        if not embedding or len(embedding)>8192 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in embedding):
            raise ValueError('Embedding响应格式无效。')
        norm=math.sqrt(sum(x*x for x in embedding))
        if not math.isfinite(norm) or norm<=0:raise ValueError('Embedding为空向量。')
        result.append({'model':model,'space':hashlib.sha256((data['endpoint']+'|'+model).encode()).hexdigest(),'values':[x/norm for x in embedding]})
    return result


def enabled(db,account,thread):
    row=db.execute('SELECT enabled,since FROM settings WHERE account=? AND thread=?',(account,thread)).fetchone()
    return row or (1,0)


def learn(root,account,thread,rows,historical=False):
    from native_controls import control_text
    from datetime import datetime
    with connect(root) as db:
        on,since=enabled(db,account,thread)
        if not on:
            if historical:raise ValueError('此对象的记忆已关闭，请先开启后再导入。')
            return
        if historical:since=0
        for row in rows:
            body=row.get('body','')
            if (row.get('accountId',account)!=account or row.get('threadId')!=thread or row.get('direction')!='incoming'
                    or row.get('type')!=1 or not isinstance(body,str) or len(body.strip())<4 or control_text(body)):
                continue
            try:stamp=datetime.fromisoformat(row.get('createdAt','').replace('Z','+00:00')).timestamp()
            except (ValueError,TypeError):continue
            if stamp<=since or db.execute('SELECT 1 FROM forgotten WHERE account=? AND thread=? AND message=?',(account,thread,row['id'])).fetchone():continue
            text=body.strip()[:1500]
            db.execute('INSERT OR IGNORE INTO memories VALUES (?,?,?,?,?,?,?,?)',(account,thread,row['id'],row.get('senderId',''),text,row.get('createdAt',''),time.time(),json.dumps(vector(text))))
        db.execute('DELETE FROM memories WHERE learned<?',(time.time()-90*86400,))
        db.execute('DELETE FROM memories WHERE account=? AND thread=? AND message NOT IN (SELECT message FROM memories WHERE account=? AND thread=? ORDER BY learned DESC,rowid DESC LIMIT 500)',(account,thread,account,thread))

    # Network calls happen outside the write transaction and only when configured.
    try:
        configured=json.loads((Path(root)/'private-data/workdesk-native-ai.json').read_text(encoding='utf-8'))
        desired=configured.get('memoryEmbeddingModel','').strip()
        space=hashlib.sha256((configured.get('endpoint','')+'|'+desired).encode()).hexdigest()
        with connect(root) as db:
            if not enabled(db,account,thread)[0]:return
            candidates=db.execute('SELECT message,body,embedding FROM memories WHERE account=? AND thread=? ORDER BY learned DESC LIMIT 12',(account,thread)).fetchall()
        candidates=[r for r in candidates if 'semantic' not in json.loads(r[2]) or (desired and (json.loads(r[2])['semantic'].get('model')!=desired or json.loads(r[2])['semantic'].get('space')!=space))]
        if candidates:
            embeddings=semantic_vectors(root,[r[1] for r in candidates])
            if embeddings:
                with connect(root) as db:
                    if not enabled(db,account,thread)[0]:return
                    for row,dense in zip(candidates,embeddings):
                        stored=json.loads(row[2]);value={'lexical':stored.get('lexical',stored),'semantic':dense}
                        db.execute('UPDATE memories SET embedding=? WHERE account=? AND thread=? AND message=?',(json.dumps(value),account,thread,row[0]))
    except (OSError,ValueError,KeyError):pass


def recall(root,account,thread,query,exclude=()):
    q=vector(query)
    with connect(root) as db:
        if not enabled(db,account,thread)[0]:return []
        rows=db.execute('SELECT message,sender,body,stamp,embedding FROM memories WHERE account=? AND thread=? AND learned>=?',(account,thread,time.time()-90*86400)).fetchall()
    try:
        dense_query=semantic_vectors(root,[query]) if any('semantic' in json.loads(r[4]) for r in rows) else None
    except (OSError,ValueError,KeyError):dense_query=None
    hits=[]
    for message,sender,body,stamp,raw in rows:
        if message in exclude:continue
        stored=json.loads(raw);lexical=stored.get('lexical',stored)
        score=sum(q.get(k,0)*v for k,v in lexical.items())
        dense=stored.get('semantic')
        if dense_query and dense and dense['model']==dense_query[0]['model'] and dense.get('space')==dense_query[0].get('space') and len(dense['values'])==len(dense_query[0]['values']):
            semantic=sum(a*b for a,b in zip(dense['values'],dense_query[0]['values']))
            score=max(score,semantic if semantic>=.6 else 0)
        if score>=.18:hits.append({'message':message,'sender':sender,'text':body,'stamp':stamp,'score':score})
    with connect(root) as db:
        if not enabled(db,account,thread)[0]:return []
        live={r[0] for r in db.execute('SELECT message FROM memories WHERE account=? AND thread=?',(account,thread))}
    return sorted((h for h in hits if h['message'] in live),key=lambda x:x['score'],reverse=True)[:4]


def inspect(root,account,thread):
    with connect(root) as db:
        on,_=enabled(db,account,thread)
        rows=db.execute('SELECT message,sender,body,stamp FROM memories WHERE account=? AND thread=? ORDER BY learned DESC,rowid DESC LIMIT 500',(account,thread)).fetchall()
    return {'enabled':bool(on),'items':[dict(zip(('message','sender','text','stamp'),r)) for r in rows]}


def manage(root,account,thread,action,message=None):
    with connect(root) as db:
        if action in ('enable','disable','clear'):
            old_on,_=enabled(db,account,thread)
            on=1 if action=='enable' else 0 if action=='disable' else old_on
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?,?,?)',(account,thread,on,time.time()))
            if action=='clear':db.execute('DELETE FROM memories WHERE account=? AND thread=?',(account,thread))
        elif action=='delete':
            db.execute('INSERT OR IGNORE INTO forgotten VALUES (?,?,?)',(account,thread,message))
            db.execute('DELETE FROM memories WHERE account=? AND thread=? AND message=?',(account,thread,message))
        else:raise ValueError('未知记忆操作。')
    return inspect(root,account,thread)
