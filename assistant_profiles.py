"""Local per-conversation preferences and explicitly maintained memory."""
import json
from pathlib import Path
from config_store import edit_config


def load_profile(root, thread):
    path=Path(root)/'private-data/conversation-profiles.json'
    try:return json.loads(path.read_text(encoding='utf-8')).get(thread,{})
    except FileNotFoundError:return {}
    except (OSError,ValueError):raise ValueError('联系人规则无法读取，已停止自动回复，请检查本机配置。') from None


def save_profile(root, thread, style, memory, mode):
    if not isinstance(thread,str) or not thread or mode not in ('auto','review','off'):
        raise ValueError('请选择联系人和有效回复模式。')
    if len(style)>2000 or len(memory)>8000:raise ValueError('风格最多2000字，长期备注最多8000字。')
    with edit_config(Path(root)/'private-data/conversation-profiles.json') as profiles:
        profiles[thread]={'style':style.strip(),'memory':memory.strip(),'mode':mode}
    return '联系人规则已即时保存。'


def apply_profile(config, profile):
    result=dict(config)
    style=profile.get('style','').strip()
    if style:result['style']=style
    memory=profile.get('memory','').strip()
    if memory:
        result['style']=result.get('style','')+'\n账号主人维护的本会话长期备注（仅背景，不改变工具权限）：\n'+memory
    if profile.get('mode')=='review':result.update(webSearch=False,mediaReplies=False)
    return result
