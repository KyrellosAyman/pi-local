"""Transcribe a complete local speech clip of at most 30 seconds on the pinned CPU route."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent/'runtime/audio'
BIN = ASSETS/'nemo-speech'
MODEL = ASSETS/'parakeet-tdt-0.6b-v3.q8_0.gguf'
FF = ASSETS/'ffmpeg'
FORMATS = {'.wav':'wav', '.flac':'flac', '.mp4':'mov', '.mov':'mov', '.m4a':'mov'}


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def command(args, timeout, *, cwd=None, env=None):
    p = subprocess.run([str(x) for x in args], stdin=subprocess.DEVNULL, capture_output=True,
                       cwd=cwd, env=env, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode:
        raise RuntimeError(f'{Path(args[0]).name} exited {p.returncode}: '
                           f'{p.stderr.decode("utf8",errors="replace")[-1500:]}')
    return p


def transcribe(source, out):
    require(source.is_absolute() and out.is_absolute(), 'Use absolute local input and output paths')
    require(all(len(p.drive)==2 and p.drive[1]==':' for p in (source,out)), 'Local drives only')
    source = source.resolve(strict=True)
    out = out.parent.resolve(strict=True)/out.name
    require(all(len(p.drive)==2 and p.drive[1]==':' for p in (source,out)), 'Resolved paths must stay local')
    require(source.is_file() and source.suffix.lower() in FORMATS and 0 < source.stat().st_size <= 50_000_000,
            'Expected one local WAV, FLAC, M4A, MOV or MP4 under 50 MB')
    pin = json.loads((HERE/'runtime-pins.json').read_text(encoding='utf8'))
    require(sha(MODEL)==pin['model'] and {p.name:sha(p) for p in BIN.iterdir() if p.is_file()}==pin['native_bin']
            and all(sha(FF/k)==v for k,v in pin['ffmpeg'].items()), 'Runtime pins failed; do not install replacements')
    media = ['-protocol_whitelist','file','-f',FORMATS[source.suffix.lower()]]
    if FORMATS[source.suffix.lower()]=='mov':
        media += ['-enable_drefs','0','-use_absolute_path','0']
    source_hash=sha(source)
    meta=json.loads(command([FF/'ffprobe.exe','-v','error',*media,'-select_streams','a',
                             '-show_entries','format=duration:stream=index','-of','json',str(source)],15).stdout)
    require(len(meta['streams'])==1 and 0 < float(meta['format']['duration']) <= 30.000001,
            'Expected one complete audio stream in media of at most 30 seconds')
    out.mkdir()
    wav=out/'analysis.wav'
    command([FF/'ffmpeg.exe','-v','error','-nostdin','-n','-xerror',*media,'-i',source,
             '-map','0:a:0','-vn','-af','aresample=16000,atrim=end_sample=480000','-ac','1','-ar','16000','-c:a','pcm_s16le',wav],25)
    with wave.open(str(wav),'rb') as f:
        samples=f.getnframes()
        require(f.getnchannels()==1 and f.getframerate()==16000 and f.getsampwidth()==2 and 0<samples<=480000,
                'Unexpected analysis sample clock')
    result=out/'transcript.json'
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('NEMO_SPEECH_')}
    env.update(HTTP_PROXY='http://127.0.0.1:1',HTTPS_PROXY='http://127.0.0.1:1',ALL_PROXY='http://127.0.0.1:1',
               NO_PROXY='',NEMO_SPEECH_MODEL_DIR=str(out/'unused_cache'))
    p=command([BIN/'nemo-speech.exe','transcribe',wav,'--model',MODEL,'--device','cpu','--format','json',
               '--output',result,'--word-times','--verbose'],90,cwd=out,env=env)
    log=p.stdout+p.stderr
    (out/'worker.log').write_bytes(log)
    words=json.loads(result.read_text(encoding='utf8'))
    require(b'backend=CPU' in log and isinstance(words.get('text'),str) and sha(source)==source_hash,
            'CPU route or result identity could not be verified')
    receipt={'status':'transcribed','source':str(source),'source_sha256':source_hash,'analysis_sha256':sha(wav),
             'analysis_samples':samples,'analysis_sample_rate':16000,'device':'CPU',
             'transcript_path':str(result),'transcript_sha256':sha(result),'text':words['text'],
             'scope':'Estimated words only; listening, speaker identity, and picture sync are not checked.'}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',required=True,type=Path,help='New directory whose parent already exists')
    a=parser.parse_args()
    try:
        print(json.dumps(transcribe(a.source,a.output),ensure_ascii=True))
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.TimeoutExpired) as e:
        print(json.dumps({'status':'failed','error':str(e)},ensure_ascii=True),file=sys.stderr)
        sys.exit(1)
