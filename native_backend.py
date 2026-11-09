"""Loopback Agent WeChat adapter; never activates or types into desktop windows."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid


def key(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


class NativeConnection:
    def __init__(self, settings):
        self.root = Path(settings['directory'])
        self.account = settings['account']
        self.base = 'http://127.0.0.1:6175/v1/accounts/' + urllib.parse.quote(self.account, safe='') + '/'
        self.selected = None
        self.known = {}
        self.cursor = None
        self.history = False
        self.rows = []
        from native_images import Previews
        self.previews = Previews(self)

    def request(self, path, data=None, request_id=None):
        headers = {'Authorization': 'Bearer ' + (self.root / 'private-data/api-token').read_text().strip()}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if request_id:
            headers['idempotency-key'] = request_id
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=None if data is None else json.dumps(data).encode())
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=8) as response:
            return json.load(response)

    @staticmethod
    def writable(info):
        category = (info.get('classification') or {}).get('category')
        return info.get('id') == 'filehelper' or (info.get('kind') in ('direct', 'group') and category not in ('business', 'system'))

    def session(self, info):
        ident = info.get('id') or info['username']
        name = info.get('remark') or info.get('displayName') or info.get('nickname') or ident
        self.known[ident] = {**info, 'id': ident, 'name': name,
                             'kind': info.get('kind') or ('group' if ident.endswith('@chatroom') else 'direct')}
        last = info.get('lastMessage') or {}
        return {'id': ident, 'key': key(ident), 'name': name, 'preview': last.get('text') or '',
                'time': last.get('createdAt', ''), 'unreadCount': info.get('unreadCount') or 0,
                'unreadLabel': str(info.get('unreadCount') or '') or '',
                'muted': bool(info.get('muted'))}

    def info(self):
        try:
            return self.request('threads/' + urllib.parse.quote(self.selected, safe=''))
        except urllib.error.HTTPError as error:
            if error.code != 404 or self.selected not in self.known:
                raise
            return self.known[self.selected]

    def load(self, cursor=None):
        path = 'threads/' + urllib.parse.quote(self.selected, safe='') + '/messages?limit=50'
        if cursor:
            path += '&cursor=' + urllib.parse.quote(cursor, safe='')
        try:
            page = self.request(path)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            page = {'items': [], 'nextCursor': None}
        self.cursor = page.get('nextCursor')
        records = []
        for row in reversed(page.get('items', [])):
            body = row.get('body') or {3: '[图片]', 34: '[语音]', 43: '[视频]', 47: '[表情]'}.get(row.get('type'), '[非文字消息]')
            who = '我' if row.get('direction') == 'outgoing' else (row.get('senderName') or row.get('senderId') or '对方')
            stamp = row.get('createdAt', '').replace('T', ' ')
            records.append({'id': row['id'], 'text': f'{who} · {stamp}\n{body}',
                            'direction': row.get('direction'), 'kind': 'image' if row.get('type') == 3 else 'text'})
        self.rows = records + self.rows if cursor else records

    def snapshot(self):
        try:
            sessions = []
            cursor = None
            for _ in range(20):
                path = 'threads?limit=100' + ('&cursor=' + urllib.parse.quote(cursor, safe='') if cursor else '')
                page = self.request(path)
                sessions.extend(self.session(info) for info in page['items'])
                cursor = page.get('nextCursor')
                if not cursor:
                    break
            if not self.selected and sessions:
                self.selected = sessions[0]['id']
            if self.selected:
                info = self.info()
                current = self.session(info)
                if not any(s['id'] == self.selected for s in sessions):
                    sessions.insert(0, current)
                if not self.history:
                    self.load()
                current = {'name': current['name'], 'key': current['key'], 'binding': key(self.selected)}
            else:
                info, current = {}, None
            return {'connected': True, 'mode': 'native', 'sessions': sessions, 'current': current,
                    'records': self.previews.enrich(self.rows), 'canSearch': True, 'canHistory': bool(current),
                    'canGoBack': False, 'canSend': bool(current) and self.writable(info),
                    'canSendImage': bool(current) and self.writable(info), 'hasNativeDraft': False,
                    'detail': 'Agent WeChat 原生后台连接',
                    'sendNote': '文字和图片通过后台接口发送；手动聊天时可先暂停 AI。语音请在手机查看。'}
        except Exception:
            return {'connected': False, 'mode': 'native', 'sessions': [], 'records': [],
                    'canSend': False, 'detail': 'Agent WeChat 暂时不可用，请检查本机服务及登录状态；不会切换到前台自动操作。'}

    def select(self, ident):
        if ident not in self.known:
            raise ValueError('请先从目录或搜索结果选择联系人。')
        self.selected, self.history, self.rows, self.cursor = ident, False, [], None
        return self.snapshot()

    def search(self, query):
        if not query:
            return {'query': query, 'results': []}
        page = self.request('contacts?query=' + urllib.parse.quote(query, safe='') + '&limit=100')
        return {'query': query, 'results': [self.session(info) for info in page['items']]}

    def scroll_history(self, binding, direction):
        if not self.selected or key(self.selected) != binding:
            raise ValueError('会话已变化。')
        changed = False
        if direction == 'older':
            self.history = True
            if self.cursor:
                self.load(self.cursor)
                changed = True
        else:
            self.history = False
            changed = True
        return {**self.snapshot(), 'historyChanged': changed}

    def send(self, binding, text):
        if not self.selected or key(self.selected) != binding:
            return {'state': 'not_sent', 'detail': '会话已变化，未发送。'}
        info = self.info()
        if not self.writable(info):
            return {'state': 'not_sent', 'detail': '当前对象不是可发送的普通会话。'}
        try:
            sent = self.request('sends', {'threadId': self.selected, 'text': text}, 'workdesk-ui-' + str(uuid.uuid4()))
            deadline = time.monotonic() + 25
            while sent.get('state') in ('queued', 'running', 'preparing', 'uploading', 'submitting') and time.monotonic() < deadline:
                time.sleep(.2)
                sent = self.request('sends/' + urllib.parse.quote(sent['id'], safe=''))
            if sent.get('state') == 'accepted':
                self.history = False
                return {'state': 'observed', 'detail': '微信服务端已接受发送；不代表对方已读。'}
        except Exception:
            pass
        return {'state': 'unknown', 'detail': '发送结果暂未确认，请查看本会话或手机，勿重复发送。'}

    def open_native(self):
        return {'ok': True, 'detail': '当前已是原生后台连接，请在本页或手机查看对话。'}

    def send_image(self, binding, encoded):
        from native_images import send_image
        return send_image(self, binding, encoded)

    def close(self):
        self.previews.close()


class NativeAI:
    @staticmethod
    def process_alive(pid):
        # A stale heartbeat is not proof of process exit; never start a duplicate.
        import ctypes
        from ctypes import wintypes
        if not isinstance(pid, int) or pid <= 0:
            return False
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)

    def __init__(self, settings, config_path):
        self.root = Path(settings['directory'])
        self.config_path = config_path
        self.config = {'allContacts': True}
        self.lifecycle_lock = threading.Lock()
        self.start_requested = 0
        if (self.root / 'private-data/watchdog.enabled').exists():
            self.ensure_watchdog()

    def ensure_watchdog(self):
        path = self.root / 'private-data/watchdog-status.json'
        try:
            status = json.loads(path.read_text())
            if self.process_alive(status.get('pid')):
                return
        except (OSError, ValueError):
            pass
        python = Path(sys.executable).with_name('pythonw.exe')
        subprocess.Popen([str(python), str(Path(__file__).with_name('native_watchdog.py')), str(self.root)],
                         cwd=self.root, creationflags=subprocess.CREATE_NO_WINDOW)

    def public(self):
        status_path = self.root / 'private-data/global-status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {}
        stopping = (self.root / 'private-data/global.stop').exists()
        age = max(0, time.time() - status.get('updatedAt', 0))
        alive = self.process_alive(status.get('pid'))
        active = alive and status.get('state') in ('listening', 'retrying') and age < 60 and not stopping
        inactive_note = ('原生 AI 已手动暂停，后台守护不会自动恢复。' if stopping else
                         '原生 AI 监听进程已退出，等待后台守护恢复或手动恢复。' if not alive else
                         '原生 AI 心跳超时，进程仍在；暂无法确认正常回复。')
        return {'backend': 'native', 'enabled': active, 'allContacts': True, 'contacts': [],
                'endpoint': '', 'model': '', 'style': '', 'interval': 0, 'hasKey': True,
                'status': ('原生后台 AI 已开启：好友与普通群聊。' if active else inactive_note) +
                          ' 关闭工作台网页不会停止独立 AI 服务。',
                'metrics': {'replies': status.get('replies', 0)},
                'health': {'state': 'ready' if active else 'off', 'scanAgeSeconds': round(age, 1)}}

    def pause(self):
        (self.root / 'private-data/global.stop').touch()
        result = self.public()
        result['status'] = '正在暂停原生 AI；未发出的回复将取消，已提交发送的消息无法撤回。'
        return result

    def start(self):
        with self.lifecycle_lock:
            (self.root / 'private-data/watchdog.enabled').touch()
            self.ensure_watchdog()
            if time.monotonic() < self.start_requested:
                return {**self.public(), 'status': '原生 AI 正在启动，请稍候。'}
            return self._start()

    def _start(self):
        from ai_reply import ReplyError
        path = self.root / 'private-data/global-status.json'
        status = json.loads(path.read_text()) if path.exists() else {}
        if self.process_alive(status.get('pid')):
            if self.public()['enabled']:
                return self.public()
            raise ReplyError('监听进程尚未确认停止，请稍候再试。')
        (self.root / 'private-data/global.stop').unlink(missing_ok=True)
        python = Path(sys.executable).with_name('pythonw.exe')
        subprocess.Popen([str(python), str(self.root / 'global_listener.py')], cwd=self.root,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        self.start_requested = time.monotonic() + 15
        return {**self.public(), 'status': '已请求启动原生 AI，稍后会更新状态。'}

    def save(self, data):
        from ai_reply import ReplyError
        raise ReplyError('原生后台沿用当前 API 与回复风格，本页暂仅提供状态、暂停与恢复。')

    def close(self):
        # Independent worker remains available when the viewer closes.
        pass
