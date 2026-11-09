"""Build and sign Android previews. Never bundles local config, credentials or test fixtures."""
import base64
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.1.0-preview.1'


def run(args,**kw):
    subprocess.run([str(a) for a in args],check=True,**kw)


def main():
    sdk=Path(os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or Path.home()/'.local/share/android-sdk')
    if not (sdk/'build-tools/35.0.0/apksigner').exists():raise SystemExit('Install Android SDK platform 35 and build-tools 35.0.0 first.')
    env=os.environ.copy();env['ANDROID_HOME']=str(sdk)
    run([ROOT/'android/gradlew','--no-daemon','-p',ROOT/'android',':app:assembleRelease',':app:lint'],env=env)
    unsigned=ROOT/'android/app/build/outputs/apk/release/app-release-unsigned.apk'
    store=Path.home()/'.local/share/workdesk-android-signing'
    store.mkdir(mode=0o700,parents=True,exist_ok=True);store.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix='workdesk-android-sign-') as temporary:
        if env.get('WORKDESK_ANDROID_KEYSTORE_BASE64'):
            keystore=Path(temporary)/'release.p12';keystore.write_bytes(base64.b64decode(env['WORKDESK_ANDROID_KEYSTORE_BASE64'],validate=True));keystore.chmod(0o600)
            if not env.get('WORKDESK_ANDROID_STORE_PASSWORD'):raise SystemExit('Missing Android signing password.')
        else:
            if env.get('GITHUB_ACTIONS')=='true':raise SystemExit('Release signing secrets must be configured for CI; refusing a temporary identity.')
            keystore=store/'release.p12';password=store/'password'
            if keystore.exists() and not password.exists():raise SystemExit('Existing signing key has no password file; do not replace it.')
            if not password.exists():password.write_text(secrets.token_urlsafe(40));password.chmod(0o600)
            env['WORKDESK_ANDROID_STORE_PASSWORD']=password.read_text().strip()
            if not keystore.exists():
                run(['keytool','-genkeypair','-keystore',keystore,'-storetype','PKCS12','-alias','workdesk','-keyalg','RSA','-keysize','3072','-validity','10000',
                     '-dname','CN=Workdesk Android Preview','-storepass:env','WORKDESK_ANDROID_STORE_PASSWORD','-keypass:env','WORKDESK_ANDROID_STORE_PASSWORD'],env=env)
                keystore.chmod(0o600)
        dist=ROOT/'dist';dist.mkdir(exist_ok=True)
        aligned=Path(temporary)/'aligned.apk';tools=sdk/'build-tools/35.0.0'
        run([tools/'zipalign','-p','-f','4',unsigned,aligned])
        artifact=dist/('Workdesk-Android-v'+VERSION+'.apk')
        run([tools/'apksigner','sign','--ks',keystore,'--ks-key-alias','workdesk','--ks-pass','env:WORKDESK_ANDROID_STORE_PASSWORD',
             '--key-pass','env:WORKDESK_ANDROID_STORE_PASSWORD','--out',artifact,aligned],env=env)
        run([tools/'apksigner','verify','--verbose','--print-certs',artifact])
        (dist/(artifact.name+'.sha256')).write_text(hashlib.sha256(artifact.read_bytes()).hexdigest()+'  '+artifact.name+'\n')
        print(artifact)


if __name__=='__main__':main()
