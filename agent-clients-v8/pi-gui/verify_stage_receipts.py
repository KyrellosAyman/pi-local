"""Exercise file-bound verification in the regular Pi desktop and pinned RPC."""

from argparse import ArgumentParser
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep, time
import tkinter as tk

from app import App
import pi_backend as backend


KEY = 'local-stage-verification-fixture'
PROMPT = 'Verify result.txt. In the Pi plan, require the checkpoint `proof.json` and the verifier script `verify.py`.'
ORIGINAL, UPDATED = 'First verified output.\n', 'Second verified output.\n'
STEP = {'id': 'check', 'title': 'Verify result.txt', 'skillQuery': 'general-task',
        'checkpoint': 'proof.json', 'verifyWith': 'verify.py'}
CHECK = ('run_script', {'path': 'verify.py', 'args': ['proof.json']})
CLOSE = ('update_plan', {'steps': [{**STEP, 'status': 'completed'}]})


def manifest(text):
    return json.dumps({'finished_files': [{'path': 'result.txt', 'sha256': sha256(text.encode()).hexdigest()}]})


VERIFIER = """from hashlib import sha256
import json
from pathlib import Path
import sys
if sys.argv[1] != 'proof.json':
    print('Success without checking the planned manifest.')
    raise SystemExit(0)
if Path('permit.txt').read_text() != 'yes':
    raise SystemExit(3)
for record in json.loads(Path(sys.argv[1]).read_text())['finished_files']:
    data = Path(record['path']).read_bytes()
    assert sha256(data).hexdigest() == record['sha256']
print('Verified the manifest and result bytes.')
"""

START = [
    ('prepare_prompt', {'brief': PROMPT, 'checks': ['Run the planned file verifier']}),
    ('update_plan', {'steps': [{k: v for k, v in {**STEP, 'status': 'in_progress'}.items() if k != 'verifyWith'}]}),
    ('review_initial_plan', {'steps': [{k: v for k, v in STEP.items() if k != 'verifyWith'}]}),
    ('review_initial_plan', {}),
    ('find_skills', {'query': 'general-task'}),
    ('use_skill', {'name': 'general-task', 'reason': 'Verify a workspace file.'}),
]
STEPS = [*START, CLOSE, ('run_script', {'path': 'verify.py', 'args': ['unrelated.json']}), CLOSE,
         CHECK, CLOSE, ('write', {'path': 'permit.txt', 'content': 'yes'}), CHECK,
         ('write', {'path': 'result.txt', 'content': UPDATED}),
         ('write', {'path': 'proof.json', 'content': manifest(UPDATED)}), CLOSE, CHECK, CLOSE, CLOSE, None]


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        index = None
        try:
            assert self.path == '/v1/chat/completions' and self.headers['Authorization'] == 'Bearer ' + KEY
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            index = self.server.requests
            self.server.requests += 1
            action = self.server.actions[index]
            if index == 17:
                self.server.before_close.set()
                assert self.server.release.wait(15)
            finish, delta = 'stop', {'role': 'assistant', 'content': 'The fixture is complete.'}
            if action:
                tool, arguments = action
                assert tool in [entry['function']['name'] for entry in request['tools']], (index, tool)
                finish = 'tool_calls'
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': f'verification-{index}',
                         'type': 'function', 'function': {'name': tool, 'arguments': json.dumps(arguments)}}]}
                if index == 1:
                    duplicate = {**arguments['steps'][0], 'id': 'duplicate', 'title': 'Draft proposed in parallel'}
                    delta['tool_calls'].append({'index': 1, 'id': 'duplicate-draft', 'type': 'function',
                                               'function': {'name': tool, 'arguments': json.dumps({'steps': [duplicate]})}})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            base = {'id': 'pi-stage-verification-fixture', 'object': 'chat.completion.chunk',
                    'created': int(time()), 'model': backend.MODEL}
            for row, reason in ((delta, None), ({}, finish)):
                frame = {**base, 'choices': [{'index': 0, 'delta': row, 'finish_reason': reason}]}
                self.wfile.write(('data: ' + json.dumps(frame) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        except OSError as error:
            if index != 17:
                self.server.errors.append(repr(error))
        except Exception as error:
            self.server.errors.append(repr(error))


class MockModel:
    config = {'model': 'Qwen3.8-27B-Uncensored-noMTP-IQ4_XS.gguf'}

    def status(self):
        return {'status': 'ready', 'model': backend.MODEL}

    def key(self):
        return KEY

    def request(self, path):
        assert path == '/slots'
        return [{'is_processing': False, 'n_ctx': 64000}]


def main(early, no_plan):
    with ThreadingHTTPServer(('127.0.0.1', 0), Provider) as provider, TemporaryDirectory(prefix='pi-stage-receipt-') as tmp:
        provider.actions = [START[0], None] if no_plan else [*START, None] if early else STEPS
        provider.requests, provider.errors = 0, []
        provider.before_close, provider.release = Event(), Event()
        Thread(target=provider.serve_forever, daemon=True).start()
        prepare = backend.prepare

        def loopback(state, key, **options):
            env = prepare(state, key, **options)
            backend.profile(state, f'http://127.0.0.1:{provider.server_port}/v1', preserve_settings=True)
            return env

        backend.prepare = loopback
        backend.hermes_active = lambda: False
        workspace, state = Path(tmp) / 'work', Path(tmp) / 'state'
        workspace.mkdir()
        state.mkdir()
        for name, data in {'result.txt': ORIGINAL, 'proof.json': manifest(ORIGINAL),
                           'verify.py': VERIFIER, 'permit.txt': 'no'}.items():
            (workspace / name).write_bytes(data.encode())
        root = tk.Tk()
        ui = App(root, MockModel(), workspace, state, recover_jobs=True)
        try:
            ui.prompt.insert('1.0', PROMPT)
            ui.send_button.invoke()
            job = ui.job
            end = monotonic() + 60
            while monotonic() < end:
                root.update()
                job = job or ui.job
                if provider.before_close.is_set() and not provider.release.is_set():
                    assert ui.jobs.checkpoint(job)['plan']['steps'][0]['status'] == 'in_progress'
                    process = ui.rpc.process
                    assert process.poll() is None
                    process.kill()
                    process.wait(timeout=5)
                    provider.release.set()
                if provider.errors or (not ui.active and ui.status.get() in ('Finished','Failed','Needs review')):
                    break
                sleep(.02)
            assert not provider.errors and provider.requests == len(provider.actions), (provider.errors, provider.requests)
            assert job
            checkpoint = ui.jobs.checkpoint(job)
            text = ui.plan.get('1.0','end')
            if no_plan:
                assert ui.status.get() == 'Needs review' and checkpoint['phase'] == 'needs_review'
                assert 'plan is missing the required verification' in checkpoint['note'] and 'plan' not in checkpoint
            elif early:
                assert ui.status.get() == 'Needs review' and checkpoint['phase'] == 'needs_review'
                assert 'Required verification is still open' in checkpoint['note'] and 'Verification required' in text
            else:
                assert ui.status.get() == 'Finished' and checkpoint['phase'] == 'completed' and checkpoint['recovered'] == 1, checkpoint
                rows = [json.loads(line) for line in Path(job['session']).read_bytes().splitlines()]
                results = {m['toolCallId']: m for row in rows if (m := row.get('message', {})).get('role') == 'toolResult'}
                duplicate = results['duplicate-draft']
                assert duplicate['isError'] or duplicate['details']['reviewPending'] and duplicate['details']['steps'][0]['id'] == 'check'
                drafts = [row for row in rows if row.get('customType') == 'gui-initial-plan-draft']
                plans = [row for row in rows if row.get('customType') == 'gui-plan']
                assert len(drafts) == 1 and plans[0]['data']['initialReview']['job'] == job['id']
                assert all(results[f'verification-{i}']['isError'] for i in (2, 6, 8, 9, 10, 15))
                proof = checkpoint['plan']['steps'][0]['checkpointProof']
                assert proof == results['verification-16']['details']['checkpointProof']
                assert proof['verification']['job'] == job['id'] and proof['verification']['call'] == 'verification-16'
                assert 'checkpointProof' not in results['verification-7']['details']
                assert 'Verifier passed' in text and (workspace / 'result.txt').read_bytes() == UPDATED.encode()
            print('Verified premature settlement remains open.' if early or no_plan else
                  'Verified missing, unrelated, failed and stale proofs are rejected, and the exact passing receipt survives restart.')
        finally:
            provider.release.set()
            if ui.rpc and ui.rpc.process.poll() is None:
                ui.rpc.close()
                ui.rpc.process.wait(timeout=8)
            root.destroy()
            provider.shutdown()


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--early-stop', action='store_true')
    mode.add_argument('--no-plan', action='store_true')
    args = parser.parse_args()
    main(args.early_stop, args.no_plan)
