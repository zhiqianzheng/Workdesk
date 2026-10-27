"""Double-click launcher; subprocesses inherit no visible console."""
from pathlib import Path
import ctypes
import json
import subprocess
import time
import urllib.request
import webbrowser

root = Path(__file__).resolve().parent
pythonw = root / '.venv' / 'Scripts' / 'pythonw.exe'
session = root / '.runtime' / 'session.json'


def existing():
    try:
        data = json.loads(session.read_text(encoding='utf-8'))
        url = data['url']
        if not url.startswith('http://127.0.0.1:18765/#key='):
            return None
        request = urllib.request.Request('http://127.0.0.1:18765/api/state', headers={'Authorization': 'Bearer ' + url.split('#key=', 1)[1]})
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status == 200:
                return url
    except Exception:
        return None


try:
    url = existing()
    if not url:
        if not pythonw.is_file():
            raise RuntimeError('缺少本地运行环境，请在此目录运行 python -m venv .venv，然后安装 requirements.txt。')
        process = subprocess.Popen([str(pythonw), str(root / 'server.py'), '--no-browser'], cwd=root,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(20):
            time.sleep(0.3)
            if process.poll() is not None:
                raise RuntimeError('启动失败，端口可能已被占用。请检查已有工作台进程。')
            if session.exists():
                url = existing()
                if url:
                    break
        if not url:
            raise RuntimeError('服务启动超时。请检查微信是否有阻塞窗口。')
    webbrowser.open(url)
except Exception as error:
    ctypes.windll.user32.MessageBoxW(None, str(error), '工作台启动提示', 0x10)
