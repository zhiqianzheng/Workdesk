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
    import tkinter as tk
    from tkinter import ttk
    from PIL import Image, ImageTk
    app = tk.Tk()
    app.title('Workdesk · 连接与 AI 控制台')
    app.geometry('850x760')
    app.minsize(760, 680)
    platform = Platform()
    events = queue.Queue()
    busy = False
    widgets = []
    rows = []
    qr_stamp = None
    ttk.Style().configure('TButton', padding=7)
    frame = ttk.Frame(app, padding=20); frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Workdesk', font=('Segoe UI', 22, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='一次配置，后台聊天。账号和密钥仅保存在这台电脑。').pack(anchor='w', pady=(0, 12))
    try:
        saved_mode = json.loads((platform.runtime / 'desktop-mode.json').read_text()).get('mode', 'native')
    except (OSError, ValueError):
        saved_mode = 'native'
    mode = tk.StringVar(value=saved_mode if os.name == 'nt' and saved_mode in ('native', 'uia') else 'native')
    choice = ttk.Frame(frame); choice.pack(fill='x')
    for value, label in [('native', '后台模式（推荐，不占用键鼠）'), ('uia', '官方微信窗口模式（需自行登录）')]:
        if os.name != 'nt' and value == 'uia':
            continue
        button = ttk.Radiobutton(choice, text=label, variable=mode, value=value);button.pack(side='left', padx=6);widgets.append(button)
    status = tk.StringVar(value='首次使用：准备后台 → 扫码登录 → 打开工作台。需要自动回复时，再配置下方 AI。')
    ttk.Label(frame, textvariable=status, wraplength=780).pack(fill='x', pady=12)
    controls = ttk.Frame(frame);controls.pack(fill='x')

    def task(fn, done=None):
        nonlocal busy
        if busy:
            return
        busy = True
        for w in widgets: w.configure(state='disabled')
        status.set('正在处理，请稍候；不会操作其他软件的鼠标键盘。')
        def run():
            try: events.put((True, fn(), done))
            except Exception as error: events.put((False, str(error) if isinstance(error, ValueError) else '操作失败，请检查网络或重试。', None))
        threading.Thread(target=run, daemon=True).start()

    def button(parent, text, callback):
        b = ttk.Button(parent, text=text, command=callback);b.pack(side='left', padx=3);widgets.append(b);return b

    def prepared(online):
        status.set('已登录，可打开工作台或刷新接管对象。' if online else '后台已准备好，请点击“扫码登录”。手机可能显示 Linux 设备并挤掉原电脑微信。')
    prepare_button = button(controls, '1. 准备后台', lambda: task(platform.prepare, prepared))
    login_button = button(controls, '2. 扫码登录', lambda: task(platform.login, lambda _: status.set('登录完成，可以打开工作台。')))
    button(controls, '3. 打开工作台', lambda: task(lambda: platform.open(mode.get())))
    qr_window = tk.Toplevel(app)
    qr_window.title('手机微信扫码登录')
    qr_window.geometry('310x300')
    qr_window.withdraw()
    qr_window.protocol('WM_DELETE_WINDOW', qr_window.withdraw)
    ttk.Label(qr_window, text='请用自己的手机微信扫码并确认').pack(pady=12)
    qr = ttk.Label(qr_window);qr.pack(pady=5)
    form = ttk.LabelFrame(frame, text='可选：AI 自动回复（初次配置默认暂停）', padding=12);form.pack(fill='both', expand=True)
    fields = {}
    for name, label, default in [('endpoint','API 地址',''),('model','模型 ID',''),('apiKey','API 密钥',''),('style','回复风格','自然口语化，简短友好，根据话题回复一到三句。')]:
        row = ttk.Frame(form);row.pack(fill='x', pady=3)
        ttk.Label(row, text=label, width=12).pack(side='left')
        entry = ttk.Entry(row, show='●' if name == 'apiKey' else '');entry.insert(0, default);entry.pack(side='left', fill='x', expand=True)
        fields[name] = entry;widgets.append(entry)
    ttk.Label(form, text='地址示例：https://你的服务/v1；密钥不回显、由系统保护，再次保存留空可保留。').pack(anchor='w')
    all_chats = tk.BooleanVar(value=False)
    check = ttk.Checkbutton(form, text='接管全部好友和普通群聊（否则只回复下方选中的对象）', variable=all_chats);check.pack(anchor='w');widgets.append(check)
    selection = tk.Listbox(form, selectmode='multiple', height=5, exportselection=False);selection.pack(fill='both', expand=True);widgets.append(selection)
    actions = ttk.Frame(form);actions.pack(fill='x', pady=5)
    def show_contacts(items):
        nonlocal rows
        rows = items;selection.delete(0, 'end')
        saved_path = platform.root / 'private-data/workdesk-native-ai.json'
        saved = json.loads(saved_path.read_text(encoding='utf-8')) if saved_path.exists() else {}
        for i, item in enumerate(items):
            selection.insert('end', item.get('remark') or item.get('displayName') or item.get('nickname') or item['id'])
            if item['id'] in saved.get('contacts', []):selection.selection_set(i)
        for name in ['endpoint', 'model', 'style']:
            if name in saved:fields[name].delete(0, 'end');fields[name].insert(0, saved[name])
        all_chats.set(saved.get('allContacts', False))
        status.set('已加载最近会话；缺少对象时，请先用手机与对方聊一句，再刷新。')
    button(actions, '刷新接管对象', lambda: task(platform.contacts, show_contacts))
    def save():
        data = {name: entry.get() for name, entry in fields.items()}
        data.update(contacts=[rows[i]['id'] for i in selection.curselection()], allContacts=all_chats.get(), interval=1)
        task(lambda: platform.save(data), lambda _: (fields['apiKey'].delete(0, 'end'), status.set('配置已保存，AI 保持暂停。确认授权后点击开启。')))
    button(actions, '保存配置', save)
    consent = tk.BooleanVar(value=False)
    check = ttk.Checkbutton(form, text='允许将所选会话文字提交给上述 API，并自动发送生成的回复', variable=consent);check.pack(anchor='w');widgets.append(check)
    ai_buttons = ttk.Frame(form);ai_buttons.pack(fill='x', pady=5)
    def start():
        if not consent.get():status.set('请先确认文字提交与自动回复授权。');return
        if not (platform.root / 'private-data/workdesk-native-ai.json').exists():status.set('请先保存 AI 配置。');return
        task(lambda: platform.ai().start(), lambda r: status.set(r['status']))
    button(ai_buttons, '开启 / 恢复 AI', start)
    button(ai_buttons, '暂停 AI', lambda: task(lambda: platform.ai().pause(), lambda r: status.set(r['status'])))
    button(ai_buttons, '检查运行状态', lambda: task(lambda: platform.ai().public(), lambda r: status.set(r['status'])))
    ttk.Label(frame, text='关闭此窗口不会停止后台 AI；要停止自动回复，请点“暂停 AI”。未设置开机自启。', wraplength=780).pack(pady=8)

    def mode_changed(*_):
        if mode.get() == 'uia':
            form.pack_forget()
            prepare_button.configure(state='disabled');login_button.configure(state='disabled')
            status.set('先在官方电脑版微信登录，再点“打开工作台”。AI 在网页内配置；此模式自动发送需要微信前台且键鼠空闲。')
        else:
            form.pack(fill='both', expand=True)
            prepare_button.configure(state='normal');login_button.configure(state='normal')
    mode.trace_add('write', mode_changed)
    mode_changed()

    def poll():
        nonlocal busy, qr_stamp
        try:
            ok, result, done = events.get_nowait()
            busy = False
            for w in widgets:w.configure(state='normal')
            if mode.get() == 'uia':
                prepare_button.configure(state='disabled');login_button.configure(state='disabled')
            status.set('操作完成。' if ok else result)
            if ok and done:
                try:done(result)
                except Exception:status.set('结果显示失败，请重新检查状态。')
            if not busy:
                qr.configure(image='');qr.image=None;qr_window.withdraw()
        except queue.Empty:
            pass
        path = platform.root / 'login.png'
        if busy and path.exists():
            try:
                stamp = path.stat().st_mtime_ns
                if stamp != qr_stamp:
                    with Image.open(path) as picture:
                        picture.thumbnail((210,210));photo = ImageTk.PhotoImage(picture.copy())
                    qr.configure(image=photo);qr.image=photo;qr_stamp=stamp
                    qr_window.deiconify()
                    status.set('请用自己的手机微信扫描二维码并确认登录。')
            except OSError:
                pass
        app.after(250, poll)
    poll()
    if mode.get() == 'native':
        app.after(350, lambda: task(platform.prepare, prepared))
    app.mainloop()
