"""Owner-authored exact text commands, monitored even while AI is paused."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import urllib.parse
import urllib.request

VERBS = {'停止': 'pause', '关闭': 'pause', '暂停': 'pause', '关掉': 'pause', '关一下': 'pause',
         '开启': 'start', '打开': 'start', '恢复': 'start', '启动': 'start', '开一下': 'start'}
PREFIX = r'(?:(?:请|麻烦|帮我|给我|现在|先|暂时|立即|马上|把|将))*'
SUFFIX = r'(?:(?:功能|模式|服务|一下|吧|了|先|暂时))*'
SUBJECT = r'ai(?:自动)?回复'
VERB = '(?P<verb>' + '|'.join(VERBS) + ')'
PATTERNS = [re.compile(PREFIX + VERB + SUBJECT + SUFFIX),
            re.compile(PREFIX + SUBJECT + r'(?:功能|模式|服务)?' + VERB + SUFFIX)]


def control_text(text):
    if not isinstance(text, str) or len(text) > 80:
        return None
    text = unicodedata.normalize('NFKC', text).lower()
    text = re.sub(r'\s+', '', text).strip('。.!！,，;；')
    # Full intent grammar, never a substring search: quotations, negation,
    # questions, forwarded instructions and ordinary discussion are not commands.
    for pattern in PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            return VERBS[match['verb']]
    return None


def atomic(path, value):
    temp = path.with_suffix('.control-tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


class OwnerControls:
    def __init__(self, root):
        self.private = Path(root) / 'private-data'
        self.path = self.private / 'owner-control-state.json'
        self.stop = self.private / 'global.stop'

    def request(self, path):
        config = json.loads((self.private / 'workdesk-native-ai.json').read_text(encoding='utf-8'))
        base = 'http://127.0.0.1:6175/v1/accounts/' + urllib.parse.quote(config['account'], safe='') + '/'
        req = urllib.request.Request(base + path, headers={
            'Authorization': 'Bearer ' + (self.private / 'api-token').read_text().strip()})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
            return json.load(response)

    def poll(self):
        if not (self.private / 'workdesk-native-ai.json').exists():
            return
        config = json.loads((self.private / 'workdesk-native-ai.json').read_text(encoding='utf-8'))
        state = json.loads(self.path.read_text()) if self.path.exists() else {}
        if state.get('account') != config['account'] or 'cursor' not in state:
            # Establish a fresh boundary; never execute historical chat commands.
            state = {'account': config['account'], 'cursor': str(self.request('threads?limit=1')['asOfEventCursor']),
                     'activatedAt': int(time.time()), 'pendingStart': None}
            atomic(self.path, state)
            return
        events = self.request('events?after=' + urllib.parse.quote(state['cursor'], safe='') + '&limit=200')
        for event in events.get('items', []):
            data = event.get('data', {})
            if (event.get('kind') == 'message.committed' and data.get('direction') == 'outgoing'
                    and data.get('origin') in ('live', 'catchup', 'local_send') and data.get('messageId')):
                row = self.request('messages/' + urllib.parse.quote(data['messageId'], safe=''))
                # Verify canonical message direction, type, thread, account and age.
                action = control_text(row.get('body'))
                try:
                    stamp = datetime.fromisoformat(row.get('createdAt', '').replace('Z', '+00:00')).timestamp()
                except (ValueError, TypeError):
                    stamp = 0
                if (action and row.get('direction') == 'outgoing' and row.get('type') == 1
                        and row.get('threadId') == data.get('threadId')
                        and row.get('accountId') == config['account'] and stamp >= state['activatedAt']):
                    if action == 'pause':
                        self.stop.touch()
                        state['pendingStart'] = None
                    else:
                        state['pendingStart'] = {'cursor': str(event['cursor']), 'at': stamp,
                                                 'stopStamp': self.stop.stat().st_mtime_ns if self.stop.exists() else None}
                    state['lastCommand'] = action
                    state['lastCommandAt'] = stamp
            state['cursor'] = str(event['cursor'])
            atomic(self.path, state)

    def resume_if_ready(self, listener_alive):
        if not self.path.exists():
            return False
        state = json.loads(self.path.read_text())
        pending = state.get('pendingStart')
        if not pending:
            return False
        # A later manual pause supersedes a pending start command.
        current_stamp = self.stop.stat().st_mtime_ns if self.stop.exists() else None
        if current_stamp is not None and current_stamp != pending['stopStamp']:
            state['pendingStart'] = None
            atomic(self.path, state)
            return False
        if listener_alive:
            if not self.stop.exists():
                state['pendingStart'] = None
                atomic(self.path, state)
            return False
        # The old worker is gone; discard paused-period backlog, retaining unknown
        # sends in blocked. New events after this start command remain eligible.
        path = self.private / 'native-ai-state.json'
        if path.exists():
            listener = json.loads(path.read_text())
            if listener.get('account') != state['account']:
                raise ValueError('Control account mismatch')
            for thread in listener.get('inFlight', {}):
                listener.setdefault('blocked', {})[thread] = 'interrupted_send_needs_review'
            listener.update(cursor=pending['cursor'], activatedAt=pending['at'], queue={}, inFlight={})
            atomic(path, listener)
        self.stop.unlink(missing_ok=True)
        state['pendingStart'] = None
        atomic(self.path, state)
        return True
