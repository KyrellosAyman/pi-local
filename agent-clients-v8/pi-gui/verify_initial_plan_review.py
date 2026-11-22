"""Exercise first-plan review and recovery through the pinned local RPC and Tk desktop."""
from argparse import ArgumentParser
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk

from app import App
import pi_backend as backend
from job_recovery import read_json


KEY = 'local-initial-plan-fixture'
PROMPT = 'Read labels.txt before copying it to result.txt. Verify the output matches the original exactly.'
SOURCE = b'Original label witness 46527.\n'
CHECKPOINT = 'output-checkpoint.json'
CHECKPOINT_BYTES = json.dumps({'finished_files': [
    {'path': 'result.txt', 'sha256': sha256(SOURCE).hexdigest()}
]}).encode()
FINDINGS = ['The draft missed reading the original before writing.', 'Add a separate exact comparison after writing.']


def plan(index):
    return [{'id': key, 'title': title, 'skillQuery': 'general-task',
             **({'checkpoint': CHECKPOINT} if ACCEPT and key == 'verify' else {}),
             'status': 'completed' if i < index else 'in_progress' if i == index else 'pending'}
            for i, (key, title) in enumerate([('inspect', 'Read the original labels'), ('copy', 'Copy the recorded bytes'),
                                             ('verify', 'Compare the new file with the original')])]


parser = ArgumentParser(description=__doc__)
parser.add_argument('--accept', action='store_true', help='Accept a complete draft without rewriting it.')
ACCEPT = parser.parse_args().accept
DRAFT = plan(0) if ACCEPT else [
    {'id': 'make-file', 'title': 'Handle the file task', 'skillQuery': 'general-task', 'status': 'in_progress'}]
EXPECTED_FINDINGS = [] if ACCEPT else FINDINGS
FIRST_REVIEW = 2 if ACCEPT else 3
FIRST_ROUTING = FIRST_REVIEW + 2


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        assert self.path == '/v1/chat/completions' and self.headers['Authorization'] == 'Bearer ' + KEY
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        index = len(self.server.requests)
        self.server.requests.append(payload)
        offered = [tool['function']['name'] for tool in payload['tools']]
        review = ('review_initial_plan', {} if ACCEPT else {
            'steps': [{key: value for key, value in step.items() if key != 'status'} for step in plan(0)],
            'findings': FINDINGS})
        unchanged = ('review_initial_plan', {'steps': [{key: value for key, value in DRAFT[0].items() if key != 'status'}],
                                             'findings': FINDINGS})
        find = ('find_skills', {'query': 'general-task'})
        actions = [
            ('prepare_prompt', {'brief': PROMPT, 'checks': ['Read first and compare bytes at the end']}),
            ('update_plan', {'steps': DRAFT}), *([] if ACCEPT else [unchanged]), review, review, find, find,
            ('use_skill', {'name': 'general-task', 'reason': 'Copy and verify the fixture.'}),
            ('read', {'path': 'labels.txt'}), ('update_plan', {'steps': plan(1)}),
            ('write', {'path': 'result.txt', 'content': SOURCE.decode()}),
            ('update_plan', {'steps': plan(2)}), ('read', {'path': 'result.txt'}),
            ('update_plan', {'steps': plan(3)}), None,
        ]
        try:
            action = actions[index]
            if 2 <= index < FIRST_ROUTING:
                assert offered == ['review_initial_plan'] and payload['tool_choice'] == 'required'
                schema = payload['tools'][0]['function']['parameters']
                assert 'status' not in schema['properties']['steps']['items']['properties']
                if ACCEPT:
                    assert 'steps' not in schema.get('required', []), 'An unchanged draft must accept an empty tool call.'
                assert DRAFT[0]['title'] in payload['messages'][0]['content']
            elif index >= FIRST_ROUTING:
                assert 'review_initial_plan' not in offered
            if index in (FIRST_REVIEW, FIRST_ROUTING):
                self.server.paused[index].set()
                assert self.server.release[index].wait(15)
            finish, delta = 'stop', {'role': 'assistant', 'content': 'Plan review fixture complete.'}
            if action:
                name, args = action
                assert name in offered, (index, name, offered)
                finish = 'tool_calls'
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': f'plan-review-{index}', 'type': 'function',
                         'function': {'name': name, 'arguments': json.dumps(args)}}]}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            base = {'id': 'pi-plan-review-fixture', 'object': 'chat.completion.chunk', 'model': backend.MODEL,
                    'created': int(time.time())}
            for part, reason in ((delta, None), ({}, finish)):
                frame = {**base, 'choices': [{'index': 0, 'delta': part, 'finish_reason': reason}]}
                self.wfile.write(('data: ' + json.dumps(frame) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        except OSError:
            if index not in self.server.release:
                raise
        except (AssertionError, IndexError) as error:
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


def wait_for(root, predicate, timeout=25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if predicate():
            return
        time.sleep(.02)
    raise TimeoutError('The requested plan review state did not appear.')


with ThreadingHTTPServer(('127.0.0.1', 0), Provider) as provider, tempfile.TemporaryDirectory(prefix='pi-plan-review-') as directory:
    provider.requests, provider.errors = [], []
    provider.paused = {i: threading.Event() for i in (FIRST_REVIEW, FIRST_ROUTING)}
    provider.release = {i: threading.Event() for i in provider.paused}
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    prepare = backend.prepare

    def mock_prepare(state, key, **options):
        env = prepare(state, key, **options)
        backend.profile(state, f'http://127.0.0.1:{provider.server_port}/v1', preserve_settings=True)
        return env

    backend.prepare = mock_prepare
    backend.hermes_active = lambda: False
    workspace, state = Path(directory) / 'work', Path(directory) / 'state'
    workspace.mkdir()
    state.mkdir()
    source, result = workspace / 'labels.txt', workspace / 'result.txt'
    source.write_bytes(SOURCE)
    if ACCEPT:
        (workspace / CHECKPOINT).write_bytes(CHECKPOINT_BYTES)
    root = tk.Tk()
    root.withdraw()
    ui = App(root, MockModel(), workspace, state, recover_jobs=True)
    try:
        ui.prompt.insert('1.0', PROMPT)
        ui.send_button.invoke()
        wait_for(root, lambda: provider.errors or provider.paused[FIRST_REVIEW].is_set())
        assert not provider.errors, provider.errors
        job = ui.job
        wait_for(root, lambda: 'Reviewing the initial plan' in ui.plan.get('1.0', 'end'))
        assert not result.exists()
        assert not ui.jobs.checkpoint(job).get('plan')
        for index in provider.paused:
            wait_for(root, provider.paused[index].is_set)
            if index == FIRST_ROUTING:
                assert ui.jobs.checkpoint(job)['plan']['initialReview']['findings'] == EXPECTED_FINDINGS
                wait_for(root, lambda: ui.plan_steps == plan(0))
                assert not result.exists()
            process = ui.rpc.process
            process.kill()
            process.wait(timeout=5)
            provider.release[index].set()
        wait_for(root, lambda: not ui.active and ui.status.get() in ('Finished', 'Failed', 'Needs review'))
        assert ui.status.get() == 'Finished', (ui.status.get(), provider.errors)
        assert not provider.errors and len(provider.requests) == FIRST_ROUTING + 10
        assert source.read_bytes() == result.read_bytes() == SOURCE
        assert [{k: v for k, v in step.items() if k != 'checkpointProof'} for step in ui.plan_steps] == plan(3)
        state = ui.jobs.checkpoint(job)
        assert state['phase'] == 'completed' and state['recovered'] == 2
        rows = [json.loads(line) for line in Path(job['session']).read_bytes().splitlines()]
        assert sum(row.get('message', {}).get('role') == 'user' for row in rows) == 1
        assert sum(row.get('customType') == 'gui-initial-plan-draft' for row in rows) == 1
        reviews = [row['data'] for row in rows if row.get('customType') == 'gui-plan' and row.get('data', {}).get('initialReview')]
        assert len(reviews) == 1 and reviews[0]['steps'] == plan(0) and reviews[0]['initialReview']['findings'] == EXPECTED_FINDINGS
        rejected = [row for row in rows if row.get('message', {}).get('toolName') == 'review_initial_plan'
                    and row['message'].get('isError')]
        if ACCEPT:
            assert reviews[0]['steps'] == DRAFT and not rejected
            assert (workspace / CHECKPOINT).read_bytes() == CHECKPOINT_BYTES
            assert state['plan']['steps'][-1]['checkpointProof']['sha256'] == sha256(CHECKPOINT_BYTES).hexdigest()
        else:
            assert len(rejected) == 1 and 'Put the reported corrections' in rejected[0]['message']['content'][0]['text']
        assert read_json(ui.jobs.directory / f"{job['id']}.outcome.json")['reason'] == 'completed'
        print(json.dumps({'initial_drafts': 1, 'committed_reviews': 1, 'actionable_steps': 3,
                          'recovered_before_and_after_review': True, 'later_plan_updates_skip_review': True,
                          **({'unchanged_draft_accepted': True, 'review_errors': 0} if ACCEPT else
                             {'missing_prerequisite_and_check_added': True, 'unchanged_plan_with_findings_rejected': True}),
                          'no_work_before_review': True, 'native_inference_requests': 0}))
    finally:
        for barrier in provider.release.values():
            barrier.set()
        if ui.rpc and ui.rpc.process.poll() is None:
            ui.rpc.close()
            ui.rpc.process.wait(timeout=8)
        root.destroy()
        provider.shutdown()
