"""Local Mandarin ASR for verified received voice assets; never a remote audio upload."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from native_images import binary
from native_video import ffmpeg_executable
from host_runtime import background

MAX_VOICE=8*1024*1024
def is_voice(row):
    return row.get('type')==34 and not row.get('recall')


def tools():
    folder=Path(__file__).parent/'vendor/speech'
    executable=folder/('whisper-cli.exe' if sys.platform=='win32' else 'whisper-cli')
    model=folder/'ggml-base.bin'
    if not executable.exists() or not model.exists():raise ValueError('缺少本地语音组件，请更新完整发行包。')
    return executable,model


def transcribe(raw,language='zh'):
    import wave
    import array
    if not raw or len(raw)>MAX_VOICE:raise ValueError('语音为空或超过 8 MB。')
    if language not in ('zh','en','auto'):raise ValueError('语音识别语言无效。')
    executable,model=tools()
    with tempfile.TemporaryDirectory(prefix='workdesk-voice-') as directory:
        source=Path(directory)/'voice.dat';source.write_bytes(raw);source.chmod(0o600)
        output=Path(directory)/'voice.wav';base=Path(directory)/'transcript'
        try:
            subprocess.run([ffmpeg_executable(),'-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','file,pipe',
                '-i',str(source),'-vn','-sn','-dn','-t','121','-ac','1','-ar','16000','-c:a','pcm_s16le',str(output)],
                capture_output=True,timeout=30,check=True,**background())
            with wave.open(str(output),'rb') as wav:
                if not 0<wav.getnframes()/wav.getframerate()<=120:raise ValueError('语音过长，请分段发送。')
                pcm=wav.readframes(wav.getnframes())
            samples=array.array('h',pcm)
            if not samples or sum(abs(n) for n in samples)/len(samples)<30:
                raise ValueError('没有检测到可辨认的声音，请重新录制。')
            subprocess.run([str(executable),'-m',str(model),'-f',str(output),'-l',language,'-t','4',
                '-ojf','-of',str(base),'-ng','-bs','1','-bo','1'],capture_output=True,timeout=150,check=True,**background())
            result=json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
        except (subprocess.SubprocessError,OSError):raise ValueError('语音暂不可解码或转写超时，请发送文字或重新录制。') from None
    segments=result.get('transcription',[])
    text=''.join(part.get('text','') for part in segments).strip()
    probabilities=[token['p'] for part in segments for token in part.get('tokens',[]) if isinstance(token.get('p'),(int,float))]
    if not text or (probabilities and sum(probabilities)/len(probabilities)<0.3):
        raise ValueError('这段语音没有可靠识别出来，请用文字补充。')
    return '语音自动转写（本地识别，可能有误）：'+text[:4000]+'\n涉及人名、数字、地址或重要操作时先核实，不把不清楚的内容当成事实。'


def fetch_voice(connection,row,language='zh'):
    quote=lambda s:urllib.parse.quote(s,safe='')
    actual=connection.request('messages/'+quote(row['id']))
    if actual.get('threadId')!=row.get('threadId') or not is_voice(actual):raise ValueError('语音不属于当前会话或已撤回。')
    items=connection.request('messages/'+quote(row['id'])+'/media')['items']
    assets=[a for a in items if a.get('kind')=='voice']
    if not assets:raise ValueError('此语音暂时没有可下载的音频。')
    assets.sort(key=lambda a:(a.get('variant')!='normal',a.get('state')!='available'))
    asset=assets[0]
    size=asset.get('byteLength') or asset.get('advertisedByteLength')
    if not isinstance(size,int) or not 0<size<=MAX_VOICE:raise ValueError('语音大小未知或超过 8 MB。')
    if asset.get('state')!='available' or asset.get('variant')!='normal' or asset.get('contentType')=='audio/silk':
        job=connection.request('messages/'+quote(row['id'])+'/media-transfers',{'messageId':row['id'],'quality':'normal'})
        until=time.monotonic()+30
        while job.get('state') in ('queued','running','preparing','downloading') and time.monotonic()<until:
            time.sleep(.3);job=connection.request('jobs/'+quote(job['id']))
        if not job.get('assetId'):raise ValueError('语音仍在下载，请稍后重试。')
        asset=connection.request('media/'+quote(job['assetId']))
    if asset.get('kind')!='voice' or asset.get('byteLength',MAX_VOICE+1)>MAX_VOICE:raise ValueError('语音资源超出限制。')
    raw=binary(connection,'media/'+quote(asset['id'])+'/content',max_bytes=MAX_VOICE)
    if len(raw)!=asset.get('byteLength') or not asset.get('sha256') or hashlib.sha256(raw).hexdigest()!=asset['sha256']:
        raise ValueError('语音完整性校验失败。')
    return transcribe(raw,language=language)


def self_check():
    fixture=Path(__file__).parent/'vendor/speech/self-test.wav'
    text=transcribe(fixture.read_bytes(),language='en').lower()
    return 'country' in text and 'ask' in text
