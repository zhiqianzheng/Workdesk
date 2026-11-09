from host_runtime import data_home, python_gui, background, lock_file
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
from native_process import command
from native_files import is_file


def key(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


SUBSCRIPTIONS = '__workdesk_subscriptions__'


class NativeConnection:
    def __init__(self, settings):
        self.root = Path(settings['directory'])
        self.account = settings['account']
        self.base = 'http://127.0.0.1:6175/v1/accounts/' + urllib.parse.quote(self.account, safe='') + '/'
        self.selected = None
        self.directory_only = False
        self.directory_view = 'root'
        self.known = {}
        self.cursor = None
        self.history = False
        self.rows = []
        self.directory = {}
        self.directory_scan = {}
        self.directory_cursor = None
        self.directory_scanning = False
        self.directory_pages = 0
        self.directory_refresh_at = 0
        from native_images import Previews
        self.previews = Previews(self)

    def request(self, path, data=None, request_id=None):
        headers = {'Authorization': 'Bearer ' + (self.root / 'private-data/api-token').read_text(encoding='utf-8').strip()}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if request_id:
            headers['idempotency-key'] = request_id
        req = urllib.request.Request(self.base + path if path else self.base.rstrip('/'), headers=headers,
                                     data=None if data is None else json.dumps(data).encode())
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as response:
            return json.load(response)

    @staticmethod
    def public_account(info):
        ident = info.get('id') or info.get('username') or ''
        return info.get('kind') != 'group' and (
            ident.startswith(('gh_', 'gh-')) or
            (info.get('classification') or {}).get('category') == 'business')

    @staticmethod
    def writable(info):
        category = (info.get('classification') or {}).get('category')
        return info.get('id') == 'filehelper' or (info.get('kind') in ('direct', 'group') and category not in ('business', 'system') and not NativeConnection.public_account(info))

    def session(self, info):
        ident = info.get('id') or info['username']
        name = info.get('remark') or info.get('displayName') or info.get('nickname') or ident
        self.known[ident] = {**info, 'id': ident, 'name': name,
                             'kind': info.get('kind') or ('group' if ident.endswith('@chatroom') else 'direct')}
        last = info.get('lastMessage') or {}
        return {'id': ident, 'key': key(ident), 'name': name, 'preview': last.get('text') or '',
                'time': last.get('createdAt', ''), 'unreadCount': info.get('unreadCount') or 0,
                'unreadLabel': str(info.get('unreadCount') or '') or '',
                'muted': bool(info.get('muted')), 'publicAccount': self.public_account(info)}

    def visible_directory(self, sessions):
        subscriptions = [s for s in sessions if s.get('publicAccount')]
        if self.directory_view == 'subscriptions':
            return subscriptions
        ordinary = [s for s in sessions if not s.get('publicAccount')]
        if subscriptions:
            unread = sum(s.get('unreadCount', 0) for s in subscriptions)
            ordinary.insert(0, {'id': SUBSCRIPTIONS, 'key': key(SUBSCRIPTIONS),
                'name': '公众号', 'folder': 'subscriptions',
                'preview': '%s 个公众号 · 点击进入' % len(subscriptions),
                'time': '', 'unreadCount': unread, 'unreadLabel': str(unread) if unread else '',
                'muted': False})
        return ordinary

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
            if row.get('type')==49 and row.get('appMessageType')==51:
                link=row.get('link') or {}
                body='[视频号卡片 · 未读取视频画面]\n'+str(link.get('sourceName') or '')+'\n'+str(link.get('description') or '')
                body+='\n当前后台仅提供卡片信息，不提供该视频号的播放资源。'
            who = '我' if row.get('direction') == 'outgoing' else (row.get('senderName') or row.get('senderId') or '对方')
            stamp = row.get('createdAt', '').replace('T', ' ')
            records.append({'id': row['id'], 'text': f'{who} · {stamp}\n{body}',
                            'direction': row.get('direction'), 'kind': 'file' if is_file(row) else 'image' if row.get('type') == 3 else 'text'})
        self.rows = records + self.rows if cursor else records

    def refresh_directory(self):
        """Read one page per snapshot, keeping already loaded contacts visible."""
        now = time.monotonic()
        if now < self.directory_refresh_at:
            return
        if not self.directory_scanning:
            self.directory_scan = {}
            self.directory_cursor = None
            self.directory_pages = 0
            self.directory_scanning = True
        path = 'threads?limit=100'
        if self.directory_cursor:
            path += '&cursor=' + urllib.parse.quote(self.directory_cursor, safe='')
        # Back off transient failures without discarding the current page/cursor.
        self.directory_refresh_at = now + 5
        page = self.request(path)
        for info in page['items']:
            self.directory_scan[info['id']] = info
        self.directory_cursor = page.get('nextCursor')
        self.directory_pages += 1
        if self.directory_cursor and self.directory_pages < 20:
            # Newest pages first; keep older cached contacts until this scan ends.
            self.directory = {**self.directory_scan, **{
                ident: info for ident, info in self.directory.items()
                if ident not in self.directory_scan}}
            self.directory_refresh_at = time.monotonic() + 1
        else:
            self.directory = dict(self.directory_scan)
            self.directory_scanning = False
            self.directory_refresh_at = time.monotonic() + 15

    def snapshot(self):
        account = None
        try:
            account = self.request('')
            if not account.get('authenticated'):
                return self.unavailable('微信尚未登录或登录已失效，请在桌面控制台扫码登录。', False)
            if account.get('connection') != 'online':
                return self.unavailable('微信已登录，但后台连接尚未就绪，请稍候重试。', True)
            self.refresh_directory()
            sessions = [self.session(info) for info in self.directory.values()]
            ordinary = [s for s in sessions if not s.get('publicAccount')]
            if not self.selected and ordinary and not self.directory_only and self.directory_view == 'root':
                self.selected = ordinary[0]['id']
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
            return {'connected': True, 'authenticated': True, 'mode': 'native',
                    'directoryLoading': self.directory_scanning,
                    'directoryView': self.directory_view,
                    'sessions': self.visible_directory(sessions), 'current': current,
                    'records': self.previews.enrich(self.rows), 'canSearch': True, 'canHistory': bool(current),
                    'canGoBack': self.directory_view != 'root' or bool(current), 'canSend': bool(current) and self.writable(info),
                    'canSendImage': bool(current) and self.writable(info), 'hasNativeDraft': False,
                    'detail': 'Agent WeChat 已登录；会话目录正在分批加载。' if self.directory_scanning else 'Agent WeChat 原生后台连接',
                    'sendNote': '文字和图片通过后台接口发送；手动聊天时可先暂停 AI。语音请在手机查看。'}
        except TimeoutError:
            detail = '微信已登录，但读取会话超时，正在重试。' if account else '微信后台响应超时，请稍后重试。'
        except urllib.error.HTTPError as error:
            detail = ('本机后台访问凭据无效，请从桌面控制台重新准备后台。' if error.code in (401, 403)
                      else '微信后台接口返回错误（HTTP %s），请稍后重试。' % error.code)
        except (urllib.error.URLError, OSError):
            detail = '无法访问本机微信后台，请在桌面控制台检查后台运行状态。'
        except (ValueError, KeyError, TypeError):
            detail = '微信后台返回的数据格式不兼容，请检查后台组件版本。'
        return self.unavailable(detail, bool(account and account.get('authenticated')))

    @staticmethod
    def unavailable(detail, authenticated):
        return {'connected': False, 'authenticated': authenticated, 'mode': 'native',
                'sessions': [], 'records': [], 'canSend': False, 'detail': detail}

    def select(self, ident):
        if ident == SUBSCRIPTIONS:
            self.directory_view = 'subscriptions'
            self.directory_only = True
            self.selected, self.history, self.rows, self.cursor = None, False, [], None
            return self.snapshot()
        if ident not in self.known:
            raise ValueError('请先从目录或搜索结果选择联系人。')
        self.directory_only = False
        self.directory_view = 'subscriptions' if self.public_account(self.known[ident]) else 'root'
        self.selected, self.history, self.rows, self.cursor = ident, False, [], None
        return self.snapshot()

    def navigate_back(self):
        # Native mode has no foreground window to navigate: return to our root
        # directory, and keep it selected across subsequent background polls.
        self.directory_only = True
        self.directory_view = 'root'
        self.selected, self.history, self.rows, self.cursor = None, False, [], None
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

    def send_file(self, binding, payload):
        from native_files import send_file
        return send_file(self, binding, payload)

    def download_file(self, binding, message):
        import base64
        from native_files import fetch_file
        if not self.selected or key(self.selected) != binding:
            return {'state': 'not_sent', 'detail': '会话已变化。'}
        try:
            name, raw = fetch_file(self, message, self.selected)
            return {'state': 'observed', 'name': name, 'data': base64.b64encode(raw).decode('ascii')}
        except Exception:
            return {'state': 'not_sent', 'detail': '文件暂不可下载、超过 8 MB 或校验失败。'}

    def close(self):
        self.previews.close()


class NativeAI:
    @staticmethod
    def process_alive(pid):
        # A stale heartbeat is not proof of process exit; never start a duplicate.
        if os.name != 'nt':
            if not isinstance(pid, int) or pid <= 0:
                return False
            try:
                os.kill(pid, 0)
                if sys.platform.startswith('linux'):
                    try:
                        # kill(pid, 0) also succeeds for an exited, unreaped child.
                        status = Path('/proc/%s/stat' % pid).read_text(encoding='utf-8').rsplit(')', 1)[1].split()[0]
                        if status in ('Z', 'X'):
                            return False
                    except FileNotFoundError:
                        return False
                    except (OSError, IndexError):
                        pass  # A restricted procfs is not proof that a process exited.
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
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
        self.config = {'allContacts': True, 'webSearch': False}
        config_file = self.root / 'private-data/workdesk-native-ai.json'
        if config_file.exists():
            saved = json.loads(config_file.read_text(encoding='utf-8'))
            self.config = {'allContacts': saved.get('allContacts', False), 'contacts': saved.get('contacts', []), 'webSearch': saved.get('webSearch', False), 'mediaReplies': saved.get('mediaReplies', False), 'videoAnalysis':saved.get('videoAnalysis',False), 'voiceReplies':saved.get('voiceReplies',False), 'ownerAssistant':saved.get('ownerAssistant',False)}
        self.lifecycle_lock = threading.Lock()
        self.start_requested = 0
        if (self.root / 'private-data/watchdog.enabled').exists():
            self.ensure_watchdog()

    def ensure_watchdog(self):
        path = self.root / 'private-data/watchdog-status.json'
        try:
            status = json.loads(path.read_text(encoding='utf-8'))
            if self.process_alive(status.get('pid')):
                return
        except (OSError, ValueError):
            pass
        python = python_gui()
        subprocess.Popen(command('watchdog', self.root),
                         cwd=self.root, **background())

    def public(self):
        # The desktop can save a new scope while this viewer remains open.
        try:
            saved = json.loads((self.root / 'private-data/workdesk-native-ai.json').read_text(encoding='utf-8'))
            self.config = {'allContacts': saved.get('allContacts', False),
                           'contacts': saved.get('contacts', []), 'webSearch': saved.get('webSearch', False), 'mediaReplies': saved.get('mediaReplies', False), 'videoAnalysis':saved.get('videoAnalysis',False), 'voiceReplies':saved.get('voiceReplies',False), 'ownerAssistant':saved.get('ownerAssistant',False)}
        except (OSError, ValueError):
            pass
        status_path = self.root / 'private-data/global-status.json'
        status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
        stopping = (self.root / 'private-data/global.stop').exists()
        try:
            personal=json.loads((self.root/'private-data/owner-assistant-status.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):personal={}
        personal_ready=(self.process_alive(personal.get('pid')) and personal.get('state') in ('listening','working')
                        and time.time()-personal.get('updatedAt',0)<30)
        try:
            supervisor = json.loads((self.root / 'private-data/watchdog-status.json').read_text(encoding='utf-8'))
            controls_active = (self.process_alive(supervisor.get('pid'))
                               and time.time() - supervisor.get('updatedAt', 0) < 15
                               and not supervisor.get('controlError'))
        except (OSError, ValueError):
            controls_active = False
        age = max(0, time.time() - status.get('updatedAt', 0))
        alive = self.process_alive(status.get('pid'))
        active = alive and status.get('state') in ('listening', 'retrying') and age < 60 and not stopping
        inactive_note = ('原生 AI 已暂停；可点击恢复，或由本人发送“开启AI回复”恢复。' if stopping else
                         '原生 AI 监听进程已退出，等待后台守护恢复或手动恢复。' if not alive else
                         '原生 AI 心跳超时，进程仍在；暂无法确认正常回复。')
        return {'backend': 'native', 'enabled': active, 'allContacts': self.config['allContacts'], 'contacts': self.config.get('contacts', []),
                'ownerHealth':{'state':personal.get('state','off'),'ready':personal_ready,'replies':personal.get('replies',0)},
                'ownerCommands': controls_active,
                'endpoint': '', 'model': '', 'style': '', 'interval': 0, 'hasKey': True, 'webSearch': self.config.get('webSearch', False), 'mediaReplies': self.config.get('mediaReplies', False), 'videoAnalysis':self.config.get('videoAnalysis',False), 'voiceReplies':self.config.get('voiceReplies',False), 'ownerAssistant':self.config.get('ownerAssistant',False),
                'status': ('原生后台 AI 已开启，按已配置的接管范围回复。' if active else inactive_note) +
                          (' 已启用按需联网检索。' if self.config.get('webSearch') else '') +
                          (' 已启用图片回复。' if self.config.get('mediaReplies') else '') +
                          (' 已启用视频抽帧分析（不含音轨）。' if self.config.get('videoAnalysis') else '') +
                          (' 已启用本地语音转写。' if self.config.get('voiceReplies') else '') +
                          (' 文件传输助手个人通道独立开启。' if self.config.get('ownerAssistant') else '') +
                          (' 本人微信口令监听正常。' if controls_active else ' 本人微信口令监听尚未就绪。') +
                          ' 关闭工作台网页不会停止独立 AI 服务。',
                'metrics': {k: status.get(k, 0) for k in ('replies', 'active', 'queued', 'blocked')},
                'paused': stopping,
                'health': {'state': ('retrying' if status.get('state')=='retrying' else 'ready') if active else 'off', 'scanAgeSeconds': round(age, 1)}}

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
        status = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if self.process_alive(status.get('pid')):
            if self.public()['enabled']:
                return self.public()
            raise ReplyError('监听进程尚未确认停止，请稍候再试。')
        (self.root / 'private-data/global.stop').unlink(missing_ok=True)
        python = python_gui()
        subprocess.Popen((command('listener', self.root)
                          if (self.root / 'private-data/workdesk-native-ai.json').exists() else
                          [str(python), str(self.root / 'global_listener.py')]), cwd=self.root,
                         **background())
        self.start_requested = time.monotonic() + 15
        return {**self.public(), 'status': '已请求启动原生 AI，稍后会更新状态。'}

    def save(self, data):
        from ai_reply import ReplyError
        raise ReplyError('原生后台沿用当前 API 与回复风格，本页暂仅提供状态、暂停与恢复。')

    def close(self):
        # Independent worker remains available when the viewer closes.
        pass
