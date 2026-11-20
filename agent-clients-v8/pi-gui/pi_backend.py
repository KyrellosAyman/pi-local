"""Pinned local Pi RPC and read-only test replay."""
from contextlib import closing
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import site
import sqlite3
import subprocess
import sys
import threading
import uuid

HERE = Path(__file__).resolve().parent
CLIENTS = HERE.parent
ROOT = CLIENTS.parent
sys.path.insert(0, str(ROOT / 'native-qwen'))
from launcher import Launcher
from context_profile import OPTIMIZED_NARROW_SHA256
from pi_runtime import CLI, MODEL, environment, profile, runtime_config
from job_recovery import atomic_json

DESKTOP_TOOLS = ('list_windows', 'get_window_state', 'click', 'set_value',
                 'type_text', 'press_key', 'hotkey', 'scroll')
BROWSER_TOOLS = ('get_chrome_state', 'chrome_action')
ANALYSIS_TOOLS = ('inspect_input', 'view_image_file', 'sample_video', 'analyze_audio',
                  'read_document', 'read_website')
SKILL_TOOLS = ('prepare_prompt', 'find_skills', 'use_skill', 'read_skill_reference',
               'research_skill', 'save_skill', 'publish_skill')
WORKSPACE_TOOLS = ('read', 'powershell', 'run_script', 'edit', 'write', 'grep', 'find', 'ls')
TOOLS = ','.join((*WORKSPACE_TOOLS, 'mcp__windows__*', 'mcp__chrome__*'))
PNG_TOOLS = ('list_recent_pngs', 'copy_downloaded_png')
WATCH_ROOT = CLIENTS / 'pi-signed-in-image-20261116'
DEFAULT_WATCH = next((folder for folder in sorted(WATCH_ROOT.glob('run-*/evidence'), reverse=True)
                      if (folder / 'gui-admission.jsonl').is_file()), WATCH_ROOT / 'run-003/evidence')


def model_slot(server):
    slots = server.request('/slots')
    if not isinstance(slots, list) or len(slots) != 1 or not isinstance(slots[0], dict):
        raise RuntimeError('Expected one local model slot.')
    return slots[0]


def slot(server):
    return 'Idle' if model_slot(server).get('is_processing') is False else 'Busy'


class NativeStopped(RuntimeError):
    pass


def verify_available(server, watch):
    if watch and watch.active():
        raise RuntimeError('The image test is still active.')
    status = server.status()
    if status.get('status') == 'stopped':
        raise NativeStopped('The pinned local Qwen backend is stopped.')
    if status.get('status') != 'ready' or status.get('model') != MODEL:
        raise RuntimeError('The pinned local Qwen backend is unavailable.')
    expected = 'qwen3.8-27b-uncensored-nomtp-iq4_xs.gguf'
    model = Path(server.config['model']).name.lower()
    if model != expected and (model != 'qwen3.8-27b-uncensored-iq4_xs.gguf'
                              or sha256((server.directory / 'server-config.json').read_bytes()).hexdigest()
                              not in (OPTIMIZED_NARROW_SHA256, runtime_config().get('native_config_sha256'))):
        raise RuntimeError('The active model file differs from the pinned Qwen weights.')
    if hermes_active() or slot(server) != 'Idle':
        raise RuntimeError('Qwen is serving another session. Wait for that run to finish.')


def hermes_active(local_appdata=None):
    db = Path(local_appdata or os.environ['LOCALAPPDATA']) / 'hermes/profiles/qwen-local/state.db'
    try:
        db.stat()
    except FileNotFoundError:
        return False
    with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        return bool(conn.execute("select 1 from session_admissions where status!='terminal' limit 1").fetchone())


def desktop_driver():
    configured = runtime_config().get('desktop_driver')
    return Path(configured) if configured else HERE / 'runtime/cua-driver-0.49.7-local-ctrlend1/cua-driver.exe'


def command(state, browser_only=False, thinking='medium', calibration=False, *, concise_checkpoints=True):
    runtime = runtime_config()
    tools = ['mcp__windows__*' if browser_only else TOOLS, *PNG_TOOLS]
    extensions = ['--extension', str(HERE / 'agent-tools.ts')]
    if concise_checkpoints and not (browser_only or calibration):
        extensions += ['--extension', str(HERE / 'compact-checkpoint.ts')]
    if not calibration:
        tools.extend(ANALYSIS_TOOLS)
        extensions += ['--extension', str(HERE / 'analysis-tools.ts')]
    tools.extend(SKILL_TOOLS)
    selection = (['--tools', ','.join((*tools, 'update_plan'))] if browser_only or calibration else
                 ['--exclude-tools', 'bash', '--tools', '+codemode'])
    return [runtime['node'], str(CLI), '--mode', 'rpc', '--provider', 'qwen-local',
            '--model', MODEL, '--thinking', thinking, *selection,
            *extensions,
            '--no-skills', '--no-prompt-templates', '--no-themes', '--no-approve',
            '--session-dir', str(state / 'sessions')]


def prepare(state, key, browser_only=False, workspace=None, calibration=False, recover_jobs=False,
            context_window=None):
    isolated = browser_only or calibration
    agent_dir = state / ('browser-profile' if browser_only else 'calibration-profile' if calibration else 'profile')
    profile(state, target=agent_dir, preserve_settings=not isolated)
    if context_window is not None:
        if type(context_window) is not int or context_window <= 0:
            raise ValueError('The local Qwen context window is invalid.')
        models_path = agent_dir / 'models.json'
        models = json.loads(models_path.read_text(encoding='utf-8'))
        model = next(item for item in models['providers']['qwen-local']['models'] if item['id'] == MODEL)
        limits = {'contextWindow': context_window}
        if context_window == 131072:
            # Full-file tool arguments can exceed the 4,096-token text default.
            limits['maxTokens'] = 8192
        if any(model.get(key) != value for key, value in limits.items()):
            model.update(limits)
            models_path.write_text(json.dumps(models, indent=2), encoding='utf-8')
    settings_path = agent_dir / 'settings.json'
    existing_settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
    settings = dict(existing_settings)
    if not isolated:
        settings.setdefault('defaultTools', list(WORKSPACE_TOOLS))
        # Keep discovery on demand so the full connected catalog stays out of prompts.
        settings.setdefault('codemode', {'inlineBudget': 0})
    if recover_jobs:
        # Dense local tool output can use far more tokens than Pi's four-characters-per-token estimate.
        settings['compaction'] = {**settings.get('compaction', {}), 'reserveTokens': 24576, 'keepRecentTokens': 4000}
    if settings != existing_settings:
        atomic_json(settings_path, settings)
    env = environment(state, key)
    env['PI_CODING_AGENT_DIR'] = str(agent_dir)
    for name in ('HOME', 'USERPROFILE'):
        env[name] = os.environ.get(name) or os.environ['USERPROFILE']
    if os.environ.get('USERNAME'):
        env['USERNAME'] = os.environ['USERNAME']
    driver = desktop_driver()
    if browser_only and not driver.is_file():
        raise RuntimeError('Configure a compatible Windows desktop driver to use browser-only mode.')
    runtime = runtime_config()
    driver_env = {'CUA_DRIVER_RS_TELEMETRY_ENABLED': '0'}
    if calibration:
        driver_env['PI_CHROME_ORIGIN'] = 'https://chatgpt.com'
        if os.environ.get('PI_CHROME_WINDOW'):
            driver_env['PI_CHROME_WINDOW'] = str(int(os.environ['PI_CHROME_WINDOW']))
    def mcp(command, args, tools):
        return {'command': command, 'args': args, 'env': driver_env, 'timeout': 45,
                'exposure': 'hidden', 'toolExposure': dict.fromkeys(tools, 'direct')}
    chrome = mcp(runtime['python'], ['-B', str(HERE / 'chrome_attachment.py'), str(driver)], BROWSER_TOOLS)
    mcp_path = agent_dir / 'mcp.json'
    existing_mcp = json.loads(mcp_path.read_text(encoding='utf-8-sig')) if mcp_path.is_file() and not isolated else {}
    if not isinstance(existing_mcp, dict) or not isinstance(existing_mcp.get('mcpServers', {}), dict):
        raise ValueError(f'Expected a JSON object with an mcpServers object in {mcp_path}.')
    builtins = {}
    if driver.is_file():
        builtins = {'windows': chrome} if browser_only else {
            'windows': mcp(str(driver), ['mcp'], DESKTOP_TOOLS), 'chrome': chrome}
    config = {**existing_mcp, 'mcpServers': {**existing_mcp.get('mcpServers', {}), **builtins}}
    if config != existing_mcp:
        atomic_json(mcp_path, config)
    for name in re.findall(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', json.dumps(config['mcpServers'])):
        if name in os.environ:
            env.setdefault(name, os.environ[name])
    if workspace is not None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as folder:
            try:
                downloads = os.path.expandvars(winreg.QueryValueEx(folder, '{374DE290-123F-4565-9164-39C4925E467B}')[0])
            except FileNotFoundError:
                downloads = str(Path(os.environ['USERPROFILE']) / 'Downloads')
        env.update(PI_IMAGE_DOWNLOADS=downloads, PI_IMAGE_OUTPUT=str(workspace / 'output'))
    user = Path(os.environ['USERPROFILE'])
    user_python = site.getuserbase()
    env.update(PYTHONUSERBASE=user_python,
               PI_LOCAL_ANALYSIS_PYTHON=runtime['python'],
               PI_LOCAL_ANALYSIS_SCRIPT=str(HERE / 'inspect_input.py'),
               PI_LOCAL_ANALYSIS_USERBASE=user_python,
               PI_SKILL_STORE=str(state / 'profile/skills'),
               PI_SKILL_BUNDLE=str(HERE / 'skills'),
               PI_SKILL_SHARED=json.dumps([str(user / '.agents/skills'), str(user / '.codex/skills')]))
    return env


def saved_chats(state):
    chats = []
    for path in (state / 'sessions').rglob('*.jsonl'):
        try:
            with path.open(encoding='utf-8') as stream:
                header = json.loads(stream.readline())
                if header.get('type') != 'session' or not header.get('cwd'):
                    continue
                title = ''
                fallback = ''
                for line in stream:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if entry.get('type') == 'session_info' and entry.get('name'):
                        title = entry['name']
                    message = entry.get('message') or {}
                    if not fallback and message.get('role') == 'user':
                        parts = message.get('content') or []
                        text = parts if isinstance(parts, str) else ' '.join(
                            item.get('text', '') for item in parts if item.get('type') == 'text')
                        fallback = ' '.join(text.split())[:120]
                if title or fallback:
                    chats.append((path.stat().st_mtime, title or fallback, path, Path(header['cwd'])))
        except (OSError, UnicodeError, ValueError):
            continue
    return sorted(chats, key=lambda row: row[0], reverse=True)


class Watch:
    def __init__(self, directory):
        self.directory = directory
        self.admission = json.loads((directory / 'gui-admission.jsonl').read_text(encoding='utf-8'))
        self.started = datetime.fromisoformat(self.admission['submitted_utc']).timestamp()
        self.receipt = directory / 'gui-settled.json'
        self.offset = 0
        self.reported_end = False

    def active(self):
        if self.receipt.is_file():
            return False
        import psutil
        try:
            process = psutil.Process(self.admission['pid'])
            args = process.cmdline()
            return (len(args) > 3 and Path(args[1]).resolve() == CLI.resolve()
                    and args[2:4] == ['--mode', 'rpc']
                    and 0 <= self.started - process.create_time() < 60)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def read(self):
        try:
            with (self.directory / 'events.jsonl').open('rb') as stream:
                stream.seek(self.offset)
                for _ in range(420):
                    line = stream.readline()
                    if not line.endswith(b'\n'):
                        break
                    self.offset = stream.tell()
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
                caught_up = stream.tell() == os.fstat(stream.fileno()).st_size
            if not self.reported_end and caught_up and not self.active():
                self.reported_end = True
                yield {'type': 'watch_end'}
        except FileNotFoundError:
            return


class Rpc:
    def __init__(self, cwd, env, argv, emit):
        self.secret = env['PI_T03_API_KEY'].encode()
        self.emit = emit
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        self.stdout = threading.Thread(target=self._read, args=(self.process.stdout, True), daemon=True)
        self.stderr = threading.Thread(target=self._read, args=(self.process.stderr, False), daemon=True)
        self.stdout.start()
        self.stderr.start()

    def _read(self, pipe, protocol):
        for line in iter(pipe.readline, b''):
            if self.secret:
                line = line.replace(self.secret, b'[REDACTED]')
            if not protocol:
                self.emit({'type': 'local_warning', 'text': line.decode('utf-8', 'replace').strip()})
                continue
            try:
                self.emit(json.loads(line))
            except ValueError:
                self.emit({'type': 'local_warning', 'text': 'Pi returned an unreadable protocol record.'})
        if protocol:
            self.emit({'type': 'local_exit', 'code': self.process.wait()})

    def send(self, action, **fields):
        identity = uuid.uuid4().hex
        payload = {'id': identity, 'type': action, **fields}
        self.process.stdin.write(json.dumps(payload).encode('utf-8') + b'\n')
        self.process.stdin.flush()
        return identity

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
