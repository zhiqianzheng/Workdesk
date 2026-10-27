"""Portable Windows entry point: bundled runtime, local per-user session state."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

from server import PORT, ROOT, main, runtime_dir


def existing():
    try:
        saved = json.loads((runtime_dir() / 'session.json').read_text(encoding='utf-8'))
        url = saved['url']
        prefix = f'http://127.0.0.1:{PORT}/#key='
        if not isinstance(url, str) or not url.startswith(prefix):
            return None
        request = urllib.request.Request(f'http://127.0.0.1:{PORT}/api/health',
                                         headers={'Authorization': 'Bearer ' + url[len(prefix):]})
        with urllib.request.urlopen(request, timeout=2) as response:
            if json.load(response).get('app') == 'project-workdesk':
                return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def opacity_executable():
    folder = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else ROOT
    executable = folder / 'WindowOpacity' / 'WindowOpacity.exe'
    if not executable.is_file():
        raise RuntimeError('未找到 WindowOpacity/WindowOpacity.exe，请完整解压组合包。')
    return executable


def launch(with_opacity=False):
    opacity = opacity_executable() if with_opacity else None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.ReleaseMutex.argtypes = kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, False, 'Local\\WorkdeskPortableLauncher')
    if not mutex:
        raise RuntimeError('无法建立启动锁，请稍后重试。')
    acquired = kernel.WaitForSingleObject(mutex, 15000) in (0, 0x80)
    try:
        if not acquired:
            raise RuntimeError('工作台仍在启动，请稍候再打开。')
        url = existing()
        if not url:
            command = [sys.executable, '--serve', '--no-browser'] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__)), '--serve', '--no-browser']
            process = subprocess.Popen(command, cwd=Path(sys.executable).parent,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError('服务启动失败。请确认压缩包已完整解压，18765 端口未被其他工作台占用。')
                time.sleep(.2)
                url = existing()
                if url:
                    break
            if not url:
                raise RuntimeError('启动超时，请稍后双击重试。')
        if opacity:
            subprocess.Popen([str(opacity), '--background'], cwd=opacity.parent,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        webbrowser.open(url)
    finally:
        if acquired:
            kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)


def self_check(output):
    # Dependency check only. Does not capture windows, read chats, or send input.
    from bridge import Bridge
    from ocr_bridge import OCRBridge
    from media import decode_image
    from clipboard_image import ImageClipboard
    from PIL import Image
    import cv2
    import numpy
    bridge = Bridge()
    bridge.close()
    ocr = OCRBridge()
    ocr.close()
    for name in ('index.html', 'app.js', 'style.css', 'icon.svg'):
        if not (ROOT / 'web' / name).is_file():
            raise RuntimeError('Missing web resource: ' + name)
    Path(output).write_text(json.dumps({'ok': True, 'frozen': bool(getattr(sys, 'frozen', False)),
                                       'python': sys.version.split()[0], 'uiAutomation': True,
                                       'ocr': True, 'webResources': True}), encoding='utf-8')


if __name__ == '__main__':
    if '--serve' in sys.argv:
        sys.argv.remove('--serve')
        main()
    elif len(sys.argv) == 3 and sys.argv[1] == '--self-check':
        try:
            self_check(sys.argv[2])
        except Exception as error:
            Path(sys.argv[2]).write_text(json.dumps({'ok': False, 'error': str(error)}), encoding='utf-8')
            raise SystemExit(1)
    else:
        try:
            launch(with_opacity='--with-opacity' in sys.argv or Path(sys.executable).stem.casefold() == 'workdesk-plus')
        except Exception as error:
            ctypes.windll.user32.MessageBoxW(None, str(error), 'Workdesk 启动提示', 0x10)
