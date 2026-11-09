"""Child process commands for source and portable distributions."""
from pathlib import Path
import sys


def command(role, root):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--' + role, str(root)]
    python = Path(sys.executable).with_name('pythonw.exe')
    script = Path(__file__).with_name('native_listener.py' if role == 'listener' else 'native_watchdog.py')
    return [str(python), str(script), *(['--root'] if role == 'listener' else []), str(root)]
