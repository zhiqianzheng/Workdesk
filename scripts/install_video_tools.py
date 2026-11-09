"""Stage the pinned Linux video wheel, including its notices and executable."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile


def install(target):
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    metadata=json.load(urllib.request.urlopen('https://pypi.org/pypi/imageio-ffmpeg/0.6.0/json',timeout=30))
    wheel=next(a for a in metadata['urls'] if a['filename'].endswith('manylinux2014_x86_64.whl'))
    raw=urllib.request.urlopen(wheel['url'],timeout=90).read()
    if hashlib.sha256(raw).hexdigest()!=wheel['digests']['sha256']:raise ValueError('Video tools checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            if not (target/name).resolve().is_relative_to(target.resolve()):raise ValueError('Invalid wheel path')
        archive.extractall(target)
    for binary in (target/'imageio_ffmpeg/binaries').glob('ffmpeg-*'):binary.chmod(0o755)
    (target/'VIDEO-TOOLS-SOURCE.txt').write_text('imageio-ffmpeg 0.6.0\nhttps://github.com/imageio/imageio-ffmpeg/tree/v0.6.0\n'
        'FFmpeg binary and upstream source/build information: https://github.com/imageio/imageio-ffmpeg/blob/v0.6.0/tasks.py\n'
        'Wheel SHA-256: '+wheel['digests']['sha256']+'\n')


if __name__=='__main__':
    import sys
    install(sys.argv[1])
