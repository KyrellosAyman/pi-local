"""Runtime settings and profile defaults for the Pi desktop client."""

import json
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLI = HERE.parent / 'node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
MODEL = 'qwen3.8-27b-uncensored'


def runtime_config():
    return json.loads((HERE / 'runtime-config.json').read_text(encoding='utf-8'))


def environment(base, credential):
    cfg = runtime_config()
    for name in ('home', 'appdata', 'localappdata', 'tmp', 'sessions', 'profile'):
        (base / name).mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE', 'PATHEXT',
        'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'PROGRAMFILES', 'PROGRAMFILES(X86)'}}
    assert '.EXE' in env['PATHEXT'].upper().split(';')
    env.update({
        'PATH': os.pathsep.join(cfg['path_entries']),
        'HOME': str(base / 'home'), 'USERPROFILE': str(base / 'home'),
        'APPDATA': str(base / 'appdata'), 'LOCALAPPDATA': str(base / 'localappdata'),
        'TEMP': str(base / 'tmp'), 'TMP': str(base / 'tmp'),
        'PI_CODING_AGENT_DIR': str(base / 'profile'),
        'PI_CODING_AGENT_SESSION_DIR': str(base / 'sessions'),
        'PYTHONDONTWRITEBYTECODE': '1',
        'PI_OFFLINE': '1', 'PI_SKIP_VERSION_CHECK': '1', 'PI_TELEMETRY': '0',
        'PI_T03_API_KEY': credential, 'NO_PROXY': '127.0.0.1,localhost',
    })
    return env


def profile(base, endpoint=None, *, target=None, preserve_settings=False):
    target = target if target is not None else base / 'profile'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('settings.json', 'models.json'):
        value = json.loads((HERE / 'profile-defaults' / name).read_text(encoding='utf-8'))
        path = target / name
        if name == 'settings.json' and preserve_settings and path.exists():
            existing = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(existing, dict):
                raise ValueError(f'Expected a settings object in {path}.')
            value.update(existing)
            if value == existing:
                continue
        if name == 'models.json' and endpoint:
            value['providers']['qwen-local']['baseUrl'] = endpoint
        path.write_text(json.dumps(value, indent=2), encoding='utf-8')
