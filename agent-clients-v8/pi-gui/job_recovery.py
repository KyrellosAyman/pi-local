"""One durable admission for the GUI-owned Pi run."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import psutil


TERMINAL = {'completed', 'failed', 'stopped'}


def atomic_json(path, data):
    temporary = path.with_name(f'.{uuid4().hex}.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        with path.open(encoding='utf-8') as stream:
            return json.load(stream)
    except FileNotFoundError:
        return None


def session_file_path(path):
    # Use the Windows filesystem namespace for I/O while keeping ordinary paths in the ledger and RPC.
    if os.name != 'nt' or not path.is_absolute() or path.drive.startswith('\\\\?\\'):
        return path
    if path.drive.startswith('\\\\'):
        return Path('\\\\?\\UNC\\' + str(path)[2:])
    return Path('\\\\?\\' + str(path))


def last_user(session, workspace):
    """Read committed records. An incomplete trailing write must not cause a replay."""
    try:
        stream = session_file_path(session).open('rb')
    except FileNotFoundError:
        return None
    with stream:
        header = json.loads(stream.readline())
        if header.get('type') != 'session' or Path(header.get('cwd') or '.').resolve() != workspace:
            raise ValueError('The saved Pi session belongs to a different workspace.')
        latest = None
        for line in stream:
            if not line.endswith(b'\n'):
                raise ValueError('The Pi session ends in a partial record. Review it before continuing.')
            entry = json.loads(line)
            if entry.get('type') == 'message' and (entry.get('message') or {}).get('role') == 'user':
                latest = entry['id']
        return latest


class Jobs:
    def __init__(self, state):
        self.directory = state / 'recovery'
        self.directory.mkdir(exist_ok=True)
        self.sessions = (state / 'sessions').resolve()
        self.active = self.directory / 'active-job.json'

    def current(self):
        job = read_json(self.active)
        if job is None:
            return None
        if not isinstance(job, dict) or not re.fullmatch('[0-9a-f]{32}', job.get('id') or ''):
            raise ValueError('Invalid Pi recovery admission.')
        self.session_path(job['session'])
        if not Path(job['workspace']).is_absolute() or not isinstance(job['payload']['message'], str):
            raise ValueError('Invalid Pi recovery workspace or prompt.')
        if job.get('thinking') not in ('off', 'low', 'medium', 'high'):
            raise ValueError('Invalid Pi recovery reasoning setting.')
        if type(job.get('allow_wide_context', True)) is not bool:
            raise ValueError('Invalid Pi recovery context setting.')
        return job

    def session_path(self, value):
        root = session_file_path(self.sessions)
        path = session_file_path(Path(value).absolute()).resolve()
        if not path.is_relative_to(root) or path.suffix != '.jsonl':
            raise ValueError('The Pi session is outside the GUI session store.')
        return self.sessions / path.relative_to(root)

    def admit(self, session, workspace, payload, thinking, process, *, allow_wide_context=False):
        if self.current() is not None:
            raise RuntimeError('The previous Pi job still has an active recovery record.')
        path = self.session_path(session)
        workspace = workspace.resolve()
        job = {'id': uuid4().hex, 'session': str(path), 'workspace': str(workspace),
               'payload': payload, 'thinking': thinking, 'previous_user': last_user(path, workspace),
               'allow_wide_context': allow_wide_context,
               'created_at': datetime.now(timezone.utc).isoformat()}
        self.record_owner(job, process)
        atomic_json(self.active, job)
        return job

    def record_owner(self, job, process):
        owner = psutil.Process(process.pid)
        atomic_json(self.directory / f"{job['id']}.owner.json", {'pid': owner.pid, 'created': owner.create_time()})

    def owner_running(self, job):
        owner = read_json(self.directory / f"{job['id']}.owner.json")
        if owner:
            try:
                process = psutil.Process(owner['pid'])
                return process.create_time() == owner['created'] and process.is_running()
            except psutil.NoSuchProcess:
                pass
        return False

    def checkpoint(self, job):
        state = read_json(self.directory / f"{job['id']}.json") or {}
        if state and state.get('id') != job['id']:
            raise ValueError('The Pi checkpoint belongs to another job.')
        return state

    def stop_path(self, job):
        return self.directory / f"{job['id']}.stop"

    def stop(self, job):
        atomic_json(self.stop_path(job), {'stopped_at': datetime.now(timezone.utc).isoformat()})

    def archive(self, job, reason):
        active = self.current()
        if active is None or active['id'] != job['id']:
            return
        atomic_json(self.directory / f"{job['id']}.outcome.json", {'reason': reason,
                    'ended_at': datetime.now(timezone.utc).isoformat()})
        self.active.replace(self.directory / f"{job['id']}.admission.json")

    def status(self, job):
        if self.stop_path(job).is_file():
            return 'stopped'
        if self.hold_note(job):
            return 'needs_review'
        return self.checkpoint(job).get('phase')

    def hold(self, job, note):
        atomic_json(self.directory / f"{job['id']}.hold.json", {'note': note})

    def hold_note(self, job):
        return (read_json(self.directory / f"{job['id']}.hold.json") or {}).get('note')

    def retry(self, job):
        path = self.directory / f"{job['id']}.attempts.json"
        attempts = (read_json(path) or {}).get('attempts', 0)
        if attempts >= 3:
            return False
        atomic_json(path, {'attempts': attempts + 1, 'attempted_at': datetime.now(timezone.utc).isoformat()})
        return True

    def resume_prompt(self, job):
        current = last_user(self.session_path(job['session']), Path(job['workspace']).resolve())
        if current and current != job['previous_user']:
            return {'message': f"/local-pi-recover {job['id']}"}
        checkpoint = self.checkpoint(job)
        if current != job['previous_user'] or checkpoint.get('pending') or checkpoint.get('completed'):
            raise ValueError('The original prompt could not be reconciled with the saved Pi session.')
        return job['payload']
