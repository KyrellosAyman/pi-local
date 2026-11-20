"""Start a saved workspace script and retain its result independently of the Pi RPC."""
import argparse
from datetime import datetime, timezone
from hashlib import file_digest, sha256
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Annotated, Literal
from uuid import uuid4

import psutil
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from typing_extensions import TypedDict

from job_recovery import atomic_json, read_json


TAIL = 4096
SCRIPT_HOST = Path(__file__).resolve()
Status = Literal['starting', 'running', 'exited', 'failed', 'unknown']


class Result(TypedDict):
    job_id: str
    status: Status
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    output_truncated: bool
    error: str | None


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with path.open('rb') as handle:
        return file_digest(handle, 'sha256').hexdigest()


def script_command(workspace, path, args):
    script = (workspace / path).resolve(strict=True)
    if not script.is_relative_to(workspace) or not script.is_file():
        raise ValueError('Use a regular script inside the current Pi workspace.')
    if any('\0' in arg for arg in args):
        raise ValueError('Script arguments cannot contain NUL.')
    if script.suffix.lower() == '.py':
        return script, [sys.executable, '-B', str(script), *args]
    if script.suffix.lower() == '.ps1':
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        return script, [str(powershell), '-NoProfile', '-NonInteractive', '-File', str(script), *args]
    raise ValueError('Choose a saved .py or .ps1 script.')


def tail(path):
    try:
        with path.open('rb') as file:
            size = file.seek(0, os.SEEK_END)
            file.seek(max(size - TAIL, 0))
            return file.read(TAIL).decode('utf-8', 'replace'), size > TAIL
    except FileNotFoundError:
        return '', False


def worker_running(record):
    if not record:
        return False
    try:
        process = psutil.Process(record['pid'])
        return process.create_time() == record['start_time'] and process.is_running()
    except psutil.NoSuchProcess:
        return False


def poll(directory):
    launch = read_json(directory / 'launch.json')
    observed = read_json(directory / 'status.json') or {}
    phase = observed.get('status', 'starting')
    error = observed.get('error')
    if phase in ('starting', 'running') and not worker_running(launch):
        observed = read_json(directory / 'status.json') or {}
        phase = observed.get('status', 'starting')
        if phase in ('starting', 'running'):
            phase, error = 'unknown', 'The supervisor exited without a completion receipt.'
        else:
            error = observed.get('error')
    stdout, stdout_long = tail(directory / 'stdout.log')
    stderr, stderr_long = tail(directory / 'stderr.log')
    return {'job_id': directory.name, 'status': phase, 'exit_code': observed.get('exit_code'),
            'stdout_tail': stdout, 'stderr_tail': stderr, 'output_truncated': stdout_long or stderr_long,
            'error': error}


def supervisor(directory):
    info = read_json(directory / 'request.json')
    workspace = Path(info['workspace']).resolve(strict=True)
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    env.pop('PI_T03_API_KEY', None)
    state = directory / 'status.json'
    try:
        script, command = script_command(workspace, info['script'], info['args'])
        if digest(script) != info['sha256']:
            raise ValueError('The script changed between admission and start.')
        with (directory / 'stdout.log').open('xb') as stdout, (directory / 'stderr.log').open('xb') as stderr:
            child = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
            atomic_json(state, {'status': 'running', 'child_pid': child.pid, 'utc': utc()})
            code = child.wait()
        atomic_json(state, {'status': 'exited', 'exit_code': code, 'utc': utc()})
    except (OSError, ValueError) as error:
        atomic_json(state, {'status': 'failed', 'error': str(error), 'utc': utc()})


def serve(root, workspace):
    jobs = root / sha256(os.path.normcase(str(workspace)).encode()).hexdigest()
    jobs.mkdir(parents=True, exist_ok=True)
    server = FastMCP('pi_workspace_jobs')

    @server.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False))
    def start_workspace_script(path: Annotated[str, Field(min_length=1, max_length=2048)],
                               args: Annotated[list[str], Field(max_length=64)] | None = None) -> Result:
        """Start one saved workspace Python or PowerShell script in the background. Save the returned job ID and poll it for its actual exit code and output."""
        script, _ = script_command(workspace, path, args or [])
        directory = jobs / uuid4().hex
        directory.mkdir()
        atomic_json(directory / 'request.json', {'workspace': str(workspace), 'script': str(script),
                    'sha256': digest(script), 'args': args or [], 'utc': utc()})
        try:
            worker = subprocess.Popen([sys.executable, '-B', str(SCRIPT_HOST), '--worker', str(directory)],
                                      cwd=workspace, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,
                                      creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                started = psutil.Process(worker.pid).create_time()
                atomic_json(directory / 'launch.json', {'pid': worker.pid, 'start_time': started})
            except psutil.NoSuchProcess:
                pass
        except OSError as error:
            atomic_json(directory / 'status.json', {'status': 'failed', 'error': str(error), 'utc': utc()})
        return poll(directory)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                             idempotentHint=True, openWorldHint=False))
    def poll_workspace_script(job_id: Annotated[str, Field(pattern='^[0-9a-f]{32}$')]) -> Result:
        """Read this workspace's background script status, exact exit code, and bounded output tails, including after a Pi restart."""
        if not re.fullmatch('[0-9a-f]{32}', job_id):
            raise ValueError('Use the job ID returned by start_workspace_script.')
        directory = jobs / job_id
        if read_json(directory / 'request.json') is None:
            raise ValueError('This job ID does not belong to the current Pi workspace.')
        return poll(directory)

    server.run(transport='stdio')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--state', type=Path)
    mode.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        supervisor(args.worker.resolve(strict=True))
    else:
        serve(args.state.resolve(), Path.cwd().resolve(strict=True))
