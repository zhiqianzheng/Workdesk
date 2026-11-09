"""Install only on our isolated emulator. No physical devices and no real WeChat users."""
import argparse
import json
import os
import shlex
import shutil
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--integration-config',type=Path);args=parser.parse_args()
    sdk=Path(os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or Path.home()/'.local/share/android-sdk')
    env=os.environ.copy();env['ANDROID_HOME']=str(sdk);env['ANDROID_AVD_HOME']=str(ROOT/'.codex-local/android-avd')
    Path(env['ANDROID_AVD_HOME']).mkdir(mode=0o700,parents=True,exist_ok=True)
    Path(env['ANDROID_AVD_HOME']).chmod(0o700)
    avd='Workdesk_Acceptance_API30';serial='emulator-5558';adb=sdk/'platform-tools/adb'
    def adb_run(*command,raw=None,check=True):
        if command and command[0]=='shell':command=('shell',shlex.join(command[1:]))
        return subprocess.run([str(adb),'-s',serial,*command],input=raw,capture_output=True,check=check)
    subprocess.run([str(ROOT/'android/gradlew'),'--no-daemon','-p',str(ROOT/'android'),':app:assembleDebug',':app:assembleDebugAndroidTest',':fixture:assembleDebug'],env=env,check=True)
    if not (Path(env['ANDROID_AVD_HOME'])/(avd+'.ini')).exists():
        subprocess.run([str(shutil.which('avdmanager') or sdk/'cmdline-tools/latest/bin/avdmanager'),'create','avd','--name',avd,'--package','system-images;android-30;default;x86_64','--device','pixel_2'],input=b'no\n',env=env,check=True)
    # Port is dedicated to this test AVD. Refuse to touch a pre-existing emulator.
    listing=subprocess.check_output([str(adb),'devices']).decode()
    if serial in listing:raise SystemExit('Test emulator port is occupied; refusing to reuse an unknown device.')
    log=(ROOT/'.codex-local/android-emulator.log').open('wb')
    emulator=subprocess.Popen([str(sdk/'emulator/emulator'),'-avd',avd,'-port','5558','-no-window','-no-audio','-no-boot-anim','-gpu','swiftshader','-accel','on','-memory','2048','-cores','2','-no-snapshot','-wipe-data'],env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        until=time.monotonic()+220
        while time.monotonic()<until:
            if emulator.poll() is not None:raise RuntimeError('Emulator exited; see private emulator log.')
            if adb_run('shell','getprop','sys.boot_completed',check=False).stdout.strip()==b'1':break
            time.sleep(2)
        else:raise RuntimeError('Emulator boot timed out.')
        if adb_run('shell','getprop','ro.kernel.qemu').stdout.strip()!=b'1' or not serial.startswith('emulator-'):
            raise RuntimeError('Synthetic fixture may only be installed on an isolated emulator.')
        for apk in ['app/build/outputs/apk/debug/app-debug.apk','app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk']:
            adb_run('install','-r',str(ROOT/'android'/apk))
        result=adb_run('shell','am','instrument','-w','com.workdesk.android.test/com.workdesk.android.Acceptance').stdout.decode()
        print(result)
        if 'PASS ' not in result or 'FAIL ' in result:raise RuntimeError('Android acceptance failed.')
        adb_run('shell','cmd','notification','allow_listener','com.workdesk.android/.WeChatNotifications')
        time.sleep(2)
        if args.integration_config:
            # No real WeChat is installed. A fixture signed with a test key stands in for its package.
            config=json.loads(args.integration_config.read_text());config.update(scope='Workdesk test',consent=True,assist=False,web=False)
            adb_run('shell','run-as','com.workdesk.android','mkdir','-p','files')
            adb_run('shell','run-as','com.workdesk.android','sh','-c','cat > files/integration-input.json',raw=json.dumps(config).encode())
            result=adb_run('shell','am','instrument','-w','-e','integration','true','com.workdesk.android.test/com.workdesk.android.Acceptance').stdout.decode()
            if 'PASS ' not in result:raise RuntimeError('Private integration setup failed.')
            adb_run('shell','am','start','-n','com.workdesk.android/.MainActivity')
            adb_run('shell','cmd','notification','disallow_listener','com.workdesk.android/.WeChatNotifications')
            adb_run('shell','cmd','notification','allow_listener','com.workdesk.android/.WeChatNotifications')
            time.sleep(3)
            adb_run('install','-r',str(ROOT/'android/fixture/build/outputs/apk/debug/fixture-debug.apk'))
            adb_run('shell','am','broadcast','-n','com.tencent.mm/com.workdesk.fixture.FixtureReceiver','--es','title','Workdesk test','--es','text','这是一条合成验收消息，请简短回复一句话。')
            until=time.monotonic()+100;answer=b''
            while time.monotonic()<until:
                answer=adb_run('shell','run-as','com.tencent.mm','cat','files/accepted-reply.txt',check=False).stdout
                if answer and b'No such file' not in answer:break
                time.sleep(2)
            if not answer:
                adb_run('shell','uiautomator','dump','/sdcard/workdesk-test.xml',check=False)
                import xml.etree.ElementTree as ET
                tree=ET.fromstring(adb_run('shell','cat','/sdcard/workdesk-test.xml').stdout)
                print([n.get('text') for n in tree.iter('node') if n.get('text','').startswith('接管已')],flush=True)
                raise RuntimeError('Synthetic notification did not receive an API-generated reply.')
            print('Synthetic notification → live API → RemoteInput callback verified; no real WeChat messages sent.')
            # Pause, remove the receipt, and prove a fresh notification cannot cause another send.
            adb_run('shell','am','instrument','-w','-e','pause_only','true','com.workdesk.android.test/com.workdesk.android.Acceptance')
            adb_run('shell','am','start','-n','com.workdesk.android/.MainActivity')
            adb_run('shell','cmd','notification','disallow_listener','com.workdesk.android/.WeChatNotifications')
            adb_run('shell','cmd','notification','allow_listener','com.workdesk.android/.WeChatNotifications')
            time.sleep(3)
            adb_run('shell','run-as','com.tencent.mm','rm','-f','files/accepted-reply.txt')
            adb_run('shell','am','broadcast','-n','com.tencent.mm/com.workdesk.fixture.FixtureReceiver','--es','title','Workdesk test','--es','text','这条消息应在暂停后被忽略。')
            time.sleep(4)
            receipt=adb_run('shell','run-as','com.tencent.mm','test','-f','files/accepted-reply.txt',check=False)
            if receipt.returncode==0:raise RuntimeError('Paused app unexpectedly replied.')
            print('Paused notification produced no reply.')
        adb_run('shell','am','start','-n','com.workdesk.android/.MainActivity')
        time.sleep(1)
        (ROOT/'.codex-local/android-home.png').write_bytes(adb_run('exec-out','screencap','-p').stdout)
        print('Android emulator acceptance complete.')
    finally:
        adb_run('emu','kill',check=False)
        try:emulator.wait(timeout=15)
        except subprocess.TimeoutExpired:emulator.terminate()
        log.close()


if __name__=='__main__':main()
