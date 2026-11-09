"""Build a pinned portable whisper.cpp CLI and stage verified multilingual weights."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
VERSION='v1.9.5'
MODEL_SHA='60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe'


def install(target):
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    cache=ROOT/'dist/whisper-build'
    source=cache/'source'
    cache.mkdir(parents=True,exist_ok=True)
    if not source.exists():
        subprocess.run(['git','clone','--depth','1','--branch',VERSION,'https://github.com/ggml-org/whisper.cpp.git',str(source)],check=True)
    build=cache/'build'
    binary=build/('bin/Release/whisper-cli.exe' if os.name=='nt' else 'bin/whisper-cli')
    if not binary.exists():
        command=['cmake','-S',str(source),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DBUILD_SHARED_LIBS=OFF',
            '-DGGML_NATIVE=OFF','-DGGML_OPENMP=OFF','-DGGML_BACKEND_DL=OFF','-DWHISPER_BUILD_TESTS=OFF',
            '-DWHISPER_BUILD_SERVER=OFF','-DGGML_AVX=OFF','-DGGML_AVX2=OFF','-DGGML_FMA=OFF','-DGGML_F16C=OFF',
            '-DCMAKE_POLICY_DEFAULT_CMP0091=NEW','-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded']
        subprocess.run(command,check=True)
        subprocess.run(['cmake','--build',str(build),'--config','Release','--target','whisper-cli','-j','4'],check=True)
    shutil.copy2(binary,target/binary.name)
    shutil.copy2(source/'LICENSE',target/'WHISPER-LICENSE')
    shutil.copy2(source/'samples/jfk.wav',target/'self-test.wav')
    model=cache/'ggml-base.bin'
    if not model.exists() or hashlib.sha256(model.read_bytes()).hexdigest()!=MODEL_SHA:
        urllib.request.urlretrieve('https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin?download=true',model)
    if hashlib.sha256(model.read_bytes()).hexdigest()!=MODEL_SHA:raise ValueError('Whisper model SHA-256 mismatch')
    shutil.copy2(model,target/'ggml-base.bin')
    (target/'SOURCE.txt').write_text('whisper.cpp '+VERSION+' (MIT)\nhttps://github.com/ggml-org/whisper.cpp/tree/'+VERSION+
        '\nMultilingual base model: https://huggingface.co/ggerganov/whisper.cpp\nSHA-256 '+MODEL_SHA+'\n')


if __name__=='__main__':
    import sys
    install(sys.argv[1])
