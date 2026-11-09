from host_runtime import data_home, python_gui, background, lock_file
"""Local listener supervisor. Never activates windows or sends messages itself."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from native_backend import NativeAI
from native_process import command
from native_controls import OwnerControls


class Supervisor:
    def __init__(self, root):
        self.root = Path(root)
        self.private = self.root / 'private-data'
        self.child = None
        self.next_start = 0
        self.attempts = 0
        self.healthy_since = None
        self.controls = OwnerControls(root)
        self.owner_child = None
        self.owner_attempts = 0
        self.owner_next_start = 0

    def ensure_owner(self):
        path=self.private/'workdesk-native-ai.json'
        if not path.exists() or json.loads(path.read_text()).get('ownerAssistant') is not True:return
        status_path=self.private/'owner-assistant-status.json'
        status=json.loads(status_path.read_text()) if status_path.exists() else {}
        if NativeAI.process_alive(status.get('pid')) or (self.owner_child is not None and self.owner_child.poll() is None):
            if status.get('state') in ('listening','working') and time.time()-status.get('updatedAt',0)<30:self.owner_attempts=0
            return
        if time.monotonic()<self.owner_next_start:return
        self.owner_attempts+=1
        self.owner_next_start=time.monotonic()+min(60,5*2**min(self.owner_attempts-1,4))
        self.owner_child=subprocess.Popen(command('owner',self.root),cwd=self.root,**background())

    def tick(self):
        if not (self.private / 'watchdog.enabled').exists():
            return 'disabled'
        try:self.ensure_owner()
        except Exception:pass  # Private-channel repair must not disable owner controls.
        # Command monitoring must survive pause and must not require an LLM.
        try:
            self.controls.poll()
            self.control_error = None
        except Exception as error:
            self.control_error = type(error).__name__
        path = self.private / 'global-status.json'
        status = json.loads(path.read_text()) if path.exists() else {}
        alive = NativeAI.process_alive(status.get('pid'))
        self.controls.resume_if_ready(alive or (self.child is not None and self.child.poll() is None))
        if (self.private / 'global.stop').exists():
            self.healthy_since = None
            return 'paused'
        # Missing/invalid status is ambiguous: do not risk a second listener.
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
        python = python_gui()
        self.child = subprocess.Popen((command('listener', self.root)
                          if (self.root / 'private-data/workdesk-native-ai.json').exists() else
                          [str(python), str(self.root / 'global_listener.py')]),
                                      cwd=self.root, **background())
        return 'restarting'


def main(root):
    guard = Supervisor(root)
    with (guard.private / 'watchdog.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            lock_file(lock)
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
                                           'updatedAt': time.time(), 'attempts': guard.attempts,
                                           'controlError': getattr(guard, 'control_error', None)}))
                os.replace(temp, guard.private / 'watchdog-status.json')
            except OSError:
                pass
            time.sleep(2)


if __name__ == '__main__':
    main(sys.argv[1])
