"""Local listener supervisor. Never activates windows or sends messages itself."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from native_backend import NativeAI


class Supervisor:
    def __init__(self, root):
        self.root = Path(root)
        self.private = self.root / 'private-data'
        self.child = None
        self.next_start = 0
        self.attempts = 0
        self.healthy_since = None

    def tick(self):
        if (self.private / 'global.stop').exists():
            self.healthy_since = None
            return 'paused'
        if not (self.private / 'watchdog.enabled').exists():
            return 'disabled'
        # Missing/invalid status is ambiguous: do not risk a second listener.
        status = json.loads((self.private / 'global-status.json').read_text())
        alive = NativeAI.process_alive(status.get('pid'))
        if alive or (self.child is not None and self.child.poll() is None):
            if time.time() - status.get('updatedAt', 0) < 60:
                self.healthy_since = self.healthy_since or time.monotonic()
                if time.monotonic() - self.healthy_since >= 60:
                    self.attempts = 0
                return 'watching'
            self.healthy_since = None
            return 'heartbeat_stale'
        self.healthy_since = None
        if time.monotonic() < self.next_start:
            return 'backoff'
        # Check pause immediately before spawning; listener also checks on entry.
        if (self.private / 'global.stop').exists():
            return 'paused'
        self.attempts += 1
        self.next_start = time.monotonic() + min(60, 5 * 2 ** min(self.attempts - 1, 4))
        python = Path(sys.executable).with_name('pythonw.exe')
        self.child = subprocess.Popen([str(python), str(self.root / 'global_listener.py')],
                                      cwd=self.root, creationflags=subprocess.CREATE_NO_WINDOW)
        return 'restarting'


def main(root):
    import msvcrt
    guard = Supervisor(root)
    with (guard.private / 'watchdog.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        while True:
            try:
                state = guard.tick()
            except Exception as error:
                state = 'retrying:' + type(error).__name__
            try:
                temp = guard.private / 'watchdog-status.tmp'
                temp.write_text(json.dumps({'pid': os.getpid(), 'state': state,
                                           'updatedAt': time.time(), 'attempts': guard.attempts}))
                os.replace(temp, guard.private / 'watchdog-status.json')
            except OSError:
                pass
            time.sleep(2)


if __name__ == '__main__':
    main(sys.argv[1])
