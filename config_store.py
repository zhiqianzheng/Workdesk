"""Serialize native configuration edits across the console and owner controls."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time
from host_runtime import lock_file


@contextmanager
def edit_config(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.edit.lock').open('a+b') as guard:
        deadline=time.monotonic()+5
        while True:
            try:guard.seek(0);lock_file(guard);break
            except OSError:
                if time.monotonic()>=deadline:raise ValueError('配置正在被其他操作修改，请稍后重试。') from None
                time.sleep(.05)
        # Windows byte-range locks also cover empty files; initialize only after locking.
        if os.fstat(guard.fileno()).st_size == 0:
            guard.write(b'0');guard.flush()
        value=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        yield value
        descriptor,temp=tempfile.mkstemp(prefix='.config-',dir=path.parent)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as out:
                json.dump(value,out,ensure_ascii=False);out.flush();os.fsync(out.fileno())
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
