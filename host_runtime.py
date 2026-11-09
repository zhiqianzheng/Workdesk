"""Platform-specific process, storage and lock primitives."""
import os
from pathlib import Path
import subprocess
import sys


def data_home():
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / 'Workdesk'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'workdesk'


def python_gui():
    return str(Path(sys.executable).with_name('pythonw.exe')) if os.name == 'nt' else sys.executable


def background():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}


def lock_file(file):
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def keyring_secret(value, decrypt=False):
    import uuid
    prefix = 'secret-service:'
    if decrypt:
        if not value.startswith(prefix):
            raise ValueError('密钥不是本机 Linux 钥匙串格式，请重新配置。')
        result = subprocess.run(['secret-tool', 'lookup', 'application', 'workdesk', 'reference', value[len(prefix):]],
                                capture_output=True, text=True, timeout=30)
        if result.returncode or not result.stdout:
            raise ValueError('无法读取系统钥匙串，请解锁登录钥匙串后重试。')
        return result.stdout.rstrip('\n')
    reference = uuid.uuid4().hex
    result = subprocess.run(['secret-tool', 'store', '--label=Workdesk AI API', 'application', 'workdesk',
                             'reference', reference], input=value, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('无法保存到系统钥匙串，请在已登录的桌面会话中解锁钥匙串。')
    return prefix + reference
