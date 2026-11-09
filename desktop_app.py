from host_runtime import data_home, python_gui, background, lock_file
"""Desktop onboarding and local service control for the portable Workdesk app."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from ai_reply import AutoReply, protect
from native_backend import NativeAI, NativeConnection
from server import runtime_dir

WX_HASH = ('01982b5d84af1f8ce2a20cb3655a2115aca5b045c586efa0ed91fd08c54e337c' if os.name == 'nt' else
           '0b59f03ace18358d0606df1eb15e0495016aabe07208da8c45dc785b70de93b3')


class Platform:
    def create_shortcut(self):
        if os.name == 'nt':
            if not getattr(sys, 'frozen', False):
                raise ValueError('请在 Windows 便携发行包中创建快捷方式。')
            script = Path(sys.executable).parent / '创建桌面快捷方式.vbs'
            subprocess.run(['cscript.exe', '//Nologo', str(script)], check=True, timeout=15,
                           capture_output=True, **background())
        else:
            result = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=5)
            desktop = Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else Path.home() / 'Desktop'
            desktop.mkdir(parents=True, exist_ok=True)
            wrapper = Path.home() / '.local/bin/workdesk'
            executable = wrapper if wrapper.is_file() else Path('/usr/bin/workdesk')
            if not executable.is_file():
                raise ValueError('请先安装 Workdesk DEB 发行包。')
            quote = lambda p: '"' + str(p).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
            icon = Path(__file__).parent / 'assets/workdesk.png'
            entry = desktop / 'Workdesk.desktop'
            entry.write_text('[Desktop Entry]\nType=Application\nName=Workdesk\nExec=' + quote(executable)
                + '\nIcon=' + str(icon) + '\nTerminal=false\nStartupWMClass=Workdesk\nCategories=Network;Utility;\n', encoding='utf-8')
            entry.chmod(0o755)
            subprocess.run(['gio', 'set', str(entry), 'metadata::trusted', 'true'], capture_output=True, timeout=5)
        return '桌面快捷方式已创建。'

    def __init__(self, root=None, runtime=None, vendor=None):
        self.root = Path(root or data_home() / 'agent')
        self.runtime = Path(runtime or runtime_dir())
        self.wx = Path(vendor or Path(__file__).parent / 'vendor' / 'agent-wechat' / ('wx.exe' if os.name == 'nt' else 'wx'))
        self.account = None
        self.connection = None

    def cli(self, *args, timeout=40):
        result = subprocess.run([str(self.wx), '--server-config', str(self.root / 'server.toml'),
                                 '--json', *args], capture_output=True, timeout=timeout,
                                **background())
        if result.returncode:
            raise ValueError('微信后台操作未完成。请确认网络正常、端口 6175 未被另一套服务占用，或重新扫码。')
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def prepare(self):
        if not self.wx.is_file() or hashlib.sha256(self.wx.read_bytes()).hexdigest() != WX_HASH:
            raise ValueError('缺少或损坏的后台组件，请完整解压官方组合包后重试。')
        self.root.mkdir(parents=True, exist_ok=True)
        private = self.root / 'private-data'
        # Generated for this installation only; never includes another user's profile.
        (self.root / 'server.toml').write_text('schemaVersion = 1\nlisten = "127.0.0.1:6175"\ndataDir = ' +
                                              json.dumps(str(private).replace('\\', '/')) + '\n', encoding='utf-8')
        self.cli('daemon', 'start')
        items = self.cli('accounts', 'list').get('items', [])
        if not items:
            self.cli('accounts', 'create', 'workdesk', '--alias', 'Workdesk')
            items = self.cli('accounts', 'list').get('items', [])
        if len(items) != 1:
            raise ValueError('此目录存在多个账号，请使用独立数据目录；本版桌面向导仅管理单个账号。')
        self.account = items[0]['id']
        self.connection = NativeConnection({'directory': str(self.root), 'account': self.account})
        return items[0].get('authenticated') and items[0].get('connection') == 'online'

    def login(self):
        if not self.account:
            self.prepare()
        qr = self.root / 'login.png'
        qr.unlink(missing_ok=True)
        self.cli('--account', self.account, 'auth', 'login', '--strategy', 'qr',
                 '--qr-refresh', 'manual', '--qr-output', str(qr), '--timeout', '180', timeout=200)
        qr.unlink(missing_ok=True)

    def contacts(self):
        if not self.connection:
            raise ValueError('请先点击“准备后台”。')
        accounts = self.cli('accounts', 'list')['items']
        if not any(x['id'] == self.account and x.get('authenticated') and x.get('connection') == 'online' for x in accounts):
            raise ValueError('请先扫码登录微信。')
        rows, cursor = [], None
        for _ in range(20):
            import urllib.parse
            page = self.connection.request('threads?limit=100' + ('&cursor=' + urllib.parse.quote(cursor, safe='') if cursor else ''))
            rows.extend(x for x in page['items'] if self.connection.writable(x) and x['id'] != 'filehelper')
            cursor = page.get('nextCursor')
            if not cursor:
                break
        return rows

    def ai(self):
        if not self.account:
            raise ValueError('请先准备后台并登录微信。')
        return NativeAI({'directory': str(self.root), 'account': self.account}, None)

    def save(self, data):
        private = self.root / 'private-data'
        self.contacts()  # Validate this account is actually connected.
        with (private / 'global-listener.lock').open('a+b') as lock:
            lock.seek(0)
            if not lock.read(1):
                lock.write(b'0'); lock.flush()
            lock.seek(0)
            try:
                lock_file(lock)
            except OSError:
                raise ValueError('AI 正在运行，请先暂停，等待退出后再保存配置。') from None
            old_path = private / 'workdesk-native-ai.json'
            old = json.loads(old_path.read_text(encoding='utf-8')) if old_path.exists() else {}
            if not data.get('apiKey') and old.get('encryptedKey'):
                data['apiKey'] = protect(old['encryptedKey'], decrypt=True)
            data.setdefault('webSearch', old.get('webSearch', False))
            data.setdefault('mediaReplies', old.get('mediaReplies', False))
            config = AutoReply.validate(data)
            if not config['allContacts'] and not config['contacts']:
                raise ValueError('请选择至少一个接管对象，或明确选择全部好友与群聊。')
            config['account'] = self.account
            key = config.pop('apiKey')
            config['encryptedKey'] = protect(key) if key else ''
            (private / 'global.stop').touch()
            temp = old_path.with_suffix('.tmp')
            temp.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, old_path)

    def session(self):
        try:
            data = json.loads((self.runtime / 'session.json').read_text())
            prefix = 'http://127.0.0.1:18765/#key='
            if not data['url'].startswith(prefix):
                return None
            self.local('/api/health', data['url'])
            return data['url']
        except (OSError, ValueError, KeyError):
            return None

    @staticmethod
    def local(path, url, payload=None):
        req = urllib.request.Request('http://127.0.0.1:18765' + path,
            headers={'Authorization': 'Bearer ' + url.split('#key=', 1)[1], 'Content-Type': 'application/json'},
            data=None if payload is None else json.dumps(payload).encode())
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5) as response:
            return json.load(response)

    def open(self, mode):
        if os.name != 'nt' and mode != 'native':
            raise ValueError('Linux 版仅支持原生后台模式。')
        path = self.runtime / 'native-backend.json'
        new = {'directory': str(self.root), 'account': self.account} if mode == 'native' else None
        if mode == 'native' and not self.account:
            raise ValueError('请先准备后台并扫码登录。')
        old = json.loads(path.read_text()) if path.exists() else None
        url = self.session()
        if old != new:
            if old:
                # Explicit mode switch pauses the previous native account first.
                NativeAI(old, None).pause()
            if url:
                self.local('/api/stop', url, {})
                for _ in range(30):
                    if not self.session():
                        break
                    time.sleep(.2)
                else:
                    raise ValueError('旧工作台尚未停止，请稍后重试。')
            self.runtime.mkdir(parents=True, exist_ok=True)
            if new:
                path.write_text(json.dumps(new), encoding='utf-8')
            elif path.exists():
                path.rename(path.with_name('native-backend-disabled-' + str(time.time_ns()) + '.json'))
            url = None
        if not url:
            cmd = [sys.executable, '--serve', '--no-browser'] if getattr(sys, 'frozen', False) else [
                str(python_gui()), str(Path(__file__).with_name('server.py')), '--no-browser']
            subprocess.Popen(cmd, **background())
            for _ in range(60):
                time.sleep(.2)
                url = self.session()
                if url:
                    break
            if not url:
                raise ValueError('网页服务未能启动，请检查端口 18765 是否被其他程序占用。')
        webbrowser.open(url)
        (self.runtime / 'desktop-mode.json').write_text(json.dumps({'mode': mode}))


def main():
    from desktop_ui import build_console
    build_console().mainloop()
