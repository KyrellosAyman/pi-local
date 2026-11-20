"""Bind a temporary wider Qwen profile to one recoverable Pi job."""
from datetime import datetime, timezone
from hashlib import sha256
import re

import pi_backend as backend
from context_profile import NARROW, PROFILE_HASHES, WIDE, qualified_wide, replace_config, restart_profile, slot_context
from job_recovery import atomic_json, read_json


def lease_file(directory):
    return directory / 'native-context-lease.json'


def failed_file(jobs, job):
    return jobs.directory / f"{job['id']}.wide-failed.json"


def qualifies(server):
    return (getattr(server, 'directory', None) is not None
            and sha256((server.directory / 'server-config.json').read_bytes()).hexdigest() in PROFILE_HASHES)


def requested(jobs, job):
    request = jobs.checkpoint(job).get('wideRequested')
    if request is None or failed_file(jobs, job).exists():
        return False
    if (not isinstance(request, dict) or request.get('context') != WIDE
            or request.get('reason') not in ('threshold', 'overflow')
            or type(request.get('tokensBefore')) is not int or request['tokensBefore'] < 0):
        raise ValueError('The stored Pi context request is invalid.')
    return True


def configs(lease):
    if (not isinstance(lease, dict) or not isinstance(lease.get('job'), str)
            or not re.fullmatch('[0-9a-f]{32}', lease['job']) or not isinstance(lease.get('narrow'), str)):
        raise ValueError('The saved native profile lease is invalid.')
    narrow = lease['narrow'].encode('utf-8')
    return narrow, qualified_wide(narrow)


def receipt(jobs, owner, stage, server):
    path = jobs.directory / f'{owner}.wide-switch.json'
    proof = read_json(path) or {}
    proof[stage] = {'at': datetime.now(timezone.utc).isoformat(), 'native_pid': server.status()['pid'],
                    'context': slot_context(server)}
    atomic_json(path, proof)


def switch_for_job(server, jobs, job):
    with server.lock():
        active = jobs.current()
        if not active or active['id'] != job['id'] or jobs.status(job) != 'running' or jobs.owner_running(job):
            raise RuntimeError('The Pi job is no longer at a safe context-switch boundary.')
        backend.verify_available(server, None)
        path = server.directory / 'server-config.json'
        current = path.read_bytes()
        file = lease_file(jobs.directory)
        lease = read_json(file)
        if lease is None:
            narrow, wide = current, qualified_wide(current)
            if slot_context(server) != NARROW:
                raise RuntimeError('The active slot is outside the qualified 64k profile.')
            lease = {'job': job['id'], 'narrow': narrow.decode('utf-8'),
                     'created_at': datetime.now(timezone.utc).isoformat()}
            atomic_json(file, lease)
            receipt(jobs, job['id'], 'before', server)
        else:
            narrow, wide = configs(lease)
            if lease['job'] != job['id']:
                raise RuntimeError('A different Pi job owns the wider context.')
        if current == wide and slot_context(server) == WIDE:
            receipt(jobs, job['id'], 'wide', server)
            return server, None
        if current != narrow:
            raise RuntimeError('The native profile changed outside the recorded context switch.')
        verify = lambda candidate: backend.verify_available(candidate, None)
        try:
            server = restart_profile(server, narrow, wide, WIDE, verify)
        except RuntimeError as error:
            restored = backend.Launcher(server.directory)
            verify(restored)
            if path.read_bytes() != narrow or slot_context(restored) != NARROW:
                raise
            note = str(error)
            atomic_json(failed_file(jobs, job), {'at': datetime.now(timezone.utc).isoformat(), 'error': note})
            file.unlink()
            return restored, note
        receipt(jobs, job['id'], 'wide', server)
        return server, None


def restore_idle(server, jobs):
    with server.lock():
        if jobs.current() or backend.hermes_active():
            return None
        file = lease_file(jobs.directory)
        lease = read_json(file)
        if lease is None:
            return server
        narrow, wide = configs(lease)
        path = server.directory / 'server-config.json'
        current = path.read_bytes()
        if current not in (narrow, wide):
            raise RuntimeError('The native profile differs from the saved Pi lease.')
        status = server.status()['status']
        if status == 'stopped':
            if server.port_owners():
                return None
            replace_config(path, narrow)
            server = backend.Launcher(server.directory)
            server.start()
        elif status != 'ready' or backend.slot(server) != 'Idle':
            return None
        elif current == wide:
            server = restart_profile(server, wide, narrow, NARROW, lambda candidate: backend.verify_available(candidate, None))
        backend.verify_available(server, None)
        if slot_context(server) != NARROW or path.read_bytes() != narrow:
            raise RuntimeError('The 64k profile could not be verified after context restoration.')
        receipt(jobs, lease['job'], 'restored', server)
        file.unlink()
        return server
