from host_runtime import data_home, python_gui, background, lock_file
"""Child process commands for source and portable distributions."""
from pathlib import Path
import sys


def command(role, root):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--' + role, str(root)]
    python = python_gui()
    script = Path(__file__).with_name('native_listener.py' if role == 'listener' else 'native_watchdog.py')
    return [str(python), str(script), *(['--root'] if role == 'listener' else []), str(root)]
