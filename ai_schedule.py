"""Prioritize changed sessions without opening every conversation on each poll."""
from collections import Counter


SYSTEM_SESSIONS = frozenset(('公众号', '服务号', '订阅号消息', '服务通知', '微信支付',
                            '微信团队', '文件传输助手', '腾讯新闻', 'QQ邮箱', '微信功能页面'))


def eligible(name, config):
    return bool(name and name not in SYSTEM_SESSIONS and
                (config.get('allContacts', False) or name in config['contacts']))


class SessionQueue:
    def __init__(self):
        self.seen = {}
        self.dirty = {}
        self.initialized = False

    def update(self, sessions, config):
        counts = Counter(s['name'] for s in sessions)
        names = set()
        for s in sessions:
            name = s['name']
            if counts[name] != 1 or not eligible(name, config):
                self.dirty.pop(name, None)
                continue
            names.add(name)
            if s.get('draft'):
                continue
            value = (s.get('preview', ''), s.get('time', ''), s.get('unreadCount') or 0)
            old = self.seen.get(name)
            # Reading a conversation clears its badge; this is not an incoming event.
            changed = old is not None and (value[:2] != old[:2] or value[2] > old[2])
            if self.initialized and (changed or old is None and value[2] > 0):
                self.dirty[name] = value
            self.seen[name] = value
        self.initialized = True
        return names

    def take(self, available, busy, current, pending):
        for name in dict.fromkeys([*self.dirty, *pending, current]):
            if name in available and name not in busy:
                return name, self.dirty.get(name)
        return None, None

    def consumed(self, name, event):
        if event is not None and self.dirty.get(name) == event:
            self.dirty.pop(name, None)


def matches_preview(rows, event):
    if not rows or not event:
        return False
    text = ''.join(rows[-1].get('text', '').split())
    preview = ''.join(event[0].split())
    if not text or not preview:
        return False
    variants = {preview, preview.split(':', 1)[-1], preview.split('：', 1)[-1]}
    return any(value.endswith(text) or (len(value) >= 12 and
               text.startswith(value.rstrip('…').rstrip('.'))) for value in variants)
