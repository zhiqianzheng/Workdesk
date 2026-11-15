"""Checksummed local preference snapshots; never restore send queues or login data."""
import hashlib
import json
from pathlib import Path
import time
import uuid
from config_store import edit_config

FIELDS=('style','contacts','allContacts','webSearch','mediaReplies','videoAnalysis','voiceReplies','voiceLanguage','groupMentionsOnly')


def create(root):
    private=Path(root)/'private-data'
    settings=json.loads((private/'workdesk-native-ai.json').read_text(encoding='utf-8'))
    try:profiles=json.loads((private/'conversation-profiles.json').read_text(encoding='utf-8'))
    except FileNotFoundError:profiles={}
    payload={'settings':{k:settings[k] for k in FIELDS if k in settings},'profiles':profiles}
    raw=json.dumps(payload,ensure_ascii=False).encode()
    folder=private/'settings-backups';folder.mkdir(exist_ok=True,mode=0o700)
    path=folder/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json')
    record={'schema':1,'sha256':hashlib.sha256(raw).hexdigest(),'payload':raw.decode()}
    path.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8');path.chmod(0o600)
    return str(path)


def inspect(root, filename):
    folder=(Path(root)/'private-data/settings-backups').resolve()
    target=Path(filename).resolve()
    if target.parent!=folder or target.is_symlink():raise ValueError('只能恢复本机备份目录中的快照。')
    if target.stat().st_size>2*1024*1024:raise ValueError('备份文件过大。')
    record=json.loads(target.read_text(encoding='utf-8'))
    if record.get('schema')!=1 or hashlib.sha256(record['payload'].encode()).hexdigest()!=record['sha256']:
        raise ValueError('备份格式或校验失败，未恢复。')
    payload=json.loads(record['payload'])
    if set(payload)!= {'settings','profiles'} or not isinstance(payload['settings'],dict) or not isinstance(payload['profiles'],dict):
        raise ValueError('备份内容格式不兼容。')
    if any(k not in FIELDS for k in payload['settings']):raise ValueError('备份含非偏好字段。')
    return payload


def restore(root,filename):
    payload=inspect(root,filename)
    # Keep an undo snapshot, with no credentials or message cursors in either file.
    undo=create(root)
    private=Path(root)/'private-data'
    with edit_config(private/'workdesk-native-ai.json') as settings:settings.update(payload['settings'])
    with edit_config(private/'conversation-profiles.json') as profiles:
        profiles.clear();profiles.update(payload['profiles'])
    return '偏好已恢复；恢复前快照：'+Path(undo).name+'。重新打开控制台查看，启动回复前请核对范围。'
