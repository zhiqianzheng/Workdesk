"""Build clean desktop releases; run with Python on the target OS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
VERSION = '1.1.0-preview.6'
HASHES = {'windows': '01982b5d84af1f8ce2a20cb3655a2115aca5b045c586efa0ed91fd08c54e337c',
          'linux': '0b59f03ace18358d0606df1eb15e0495016aabe07208da8c45dc785b70de93b3'}


def download_native(platform):
    folder = ROOT / 'vendor/agent-wechat'
    folder.mkdir(parents=True, exist_ok=True)
    suffix = 'win32-x64.exe' if platform == 'windows' else 'linux-x64-gnu'
    binary = folder / ('wx.exe' if platform == 'windows' else 'wx')
    if not binary.exists():
        urllib.request.urlretrieve('https://github.com/thisnick/agent-wechat/releases/download/v2.2.0/wx-v2.2.0-' + suffix, binary)
    if hashlib.sha256(binary.read_bytes()).hexdigest() != HASHES[platform]:
        raise ValueError('Agent WeChat SHA-256 mismatch')
    binary.chmod(0o755)
    for filename, url in {
        'LICENSE': 'https://raw.githubusercontent.com/thisnick/agent-wechat/v2.2.0/LICENSE',
        'THIRD-PARTY-NOTICES.txt': 'https://github.com/thisnick/agent-wechat/releases/download/v2.2.0/wx-v2.2.0-THIRD-PARTY-NOTICES.txt'
    }.items():
        if not (folder / filename).exists():
            urllib.request.urlretrieve(url, folder / filename)
    return folder


def copy_app(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for pattern in ('*.py', '*.pyw'):
        for source in ROOT.glob(pattern):
            shutil.copy2(source, destination / source.name)
    for name in ('web', 'third_party', 'assets'):
        shutil.copytree(ROOT / name, destination / name, dirs_exist_ok=True)
    shutil.copy2(ROOT / 'README.md', destination / 'README.md')


def linux():
    vendor = download_native('linux')
    stage = DIST / 'linux-stage'
    if stage.exists():
        shutil.rmtree(stage)
    app = stage / 'usr/lib/workdesk'
    copy_app(app)
    from install_video_tools import install
    install(app / '_vendor')
    subprocess.run([sys.executable,'-c','from native_video import self_check; assert self_check()'],cwd=app,check=True)
    shutil.copytree(vendor, app / 'vendor/agent-wechat', ignore=shutil.ignore_patterns('wx.exe'))
    control = stage / 'DEBIAN'
    control.mkdir()
    (control / 'control').write_text('''Package: workdesk
Version: {version}
Architecture: amd64
Maintainer: Workdesk Project
Section: net
Priority: optional
Depends: python3 (>= 3.10), python3-tk, python3-pil, python3-pil.imagetk, libsecret-tools, gnome-keyring, dbus-user-session, ca-certificates, xdg-utils, libc6 (>= 2.35), libgcc-s1
Description: Local Workdesk desktop and native messaging backend
 Desktop preview with optional configurable AI replies.
'''.format(version=VERSION.replace('-preview.', '~preview.')))
    launcher = stage / 'usr/bin/workdesk'
    launcher.parent.mkdir(parents=True)
    launcher.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/lib/workdesk/desktop.pyw "$@"\n')
    launcher.chmod(0o755)
    entry = stage / 'usr/share/applications/workdesk.desktop'
    entry.parent.mkdir(parents=True)
    entry.write_text('[Desktop Entry]\nType=Application\nName=Workdesk\nExec=workdesk\nIcon=workdesk\nTerminal=false\nStartupWMClass=Workdesk\nCategories=Network;Utility;\n')
    icons = stage / 'usr/share/icons/hicolor/scalable/apps'
    icons.mkdir(parents=True)
    shutil.copy2(ROOT / 'assets/workdesk.svg', icons / 'workdesk.svg')
    for size in (48, 128, 256, 512):
        from PIL import Image
        folder = stage / f'usr/share/icons/hicolor/{size}x{size}/apps'
        folder.mkdir(parents=True)
        with Image.open(ROOT / 'assets/workdesk.png') as icon:
            icon.resize((size, size), getattr(Image, 'Resampling', Image).LANCZOS).save(folder / 'workdesk.png')
    artifact = DIST / f'Workdesk_{VERSION}_amd64.deb'
    subprocess.run(['dpkg-deb', '-Zgzip', '--root-owner-group', '--build', str(stage), str(artifact)], check=True)
    return artifact


def windows():
    download_native('windows')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
               '--name', 'Workdesk', '--icon', str(ROOT / 'assets/workdesk.ico')]
    for source in ROOT.glob('*.py'):
        command += ['--hidden-import', source.stem]
    for name in ('web', 'third_party', 'assets', 'vendor/agent-wechat'):
        command += ['--add-data', str(ROOT / name) + os.pathsep + name]
    for name in ('uiautomation', 'comtypes', 'winsdk', 'windows_capture', 'imageio_ffmpeg'):
        command += ['--collect-all', name]
    command += [str(ROOT / 'desktop.pyw')]
    subprocess.run(command, cwd=ROOT, check=True)
    bundle = DIST / 'Workdesk'
    shutil.copy2(ROOT / 'README.md', bundle / 'README.md')
    shutil.copy2(ROOT / 'scripts/create-desktop-shortcut.vbs', bundle / '创建桌面快捷方式.vbs')
    env = os.environ.copy()
    isolated = DIST / 'self-check-profile'
    isolated.mkdir(exist_ok=True)
    env['LOCALAPPDATA'] = str(isolated)
    report = DIST / 'windows-self-check.json'
    process = subprocess.Popen([str(bundle / 'Workdesk.exe'), '--self-check', str(report)], env=env)
    if process.wait(timeout=60) != 0 or not report.exists() or not json.loads(report.read_text())['ok']:
        raise RuntimeError('Packaged Windows self-check failed')
    return Path(shutil.make_archive(str(DIST / f'Workdesk-Desktop-v{VERSION}-Windows-x64'), 'zip', DIST, 'Workdesk'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('platform', choices=('linux', 'windows'))
    args = parser.parse_args()
    DIST.mkdir(exist_ok=True)
    artifact = windows() if args.platform == 'windows' else linux()
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (DIST / (artifact.name + '.sha256')).write_text(checksum + '  ' + artifact.name + '\n')
    print(artifact)
