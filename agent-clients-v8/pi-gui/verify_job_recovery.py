"""Exercise the actual Pi RPC process, including a killed child and a restarted GUI."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk

from app import App
import pi_backend as backend
from job_recovery import Jobs


MODEL = backend.MODEL
OBJECTIVE = 'Use the fixture to finish both recorded outputs and verify their exact contents.'
FIRST = {'path': 'first.txt', 'content': 'original stage committed\n'}
SECOND = {'path': 'second.txt', 'content': 'resumed stage committed\n'}
TOOL_WITNESS = 'Exact script result 197429, keep unchanged.'
requests = []
recovery = 'Continue the interrupted job in this session.'
step = {'id': 'finish', 'title': 'Write and verify the outputs', 'skillQuery': 'general-task'}
bootstrap = [('prepare_prompt', {'brief': OBJECTIVE, 'checks': ['Check both files.']}),
             ('update_plan', {'steps': [{**step, 'status': 'in_progress'}]}),
             ('find_skills', {'query': 'general-task'}),
             ('use_skill', {'name': 'general-task', 'reason': 'General file work.'})]
original = [*bootstrap, ('run_script', {'path': 'proof.py'}), ('write', FIRST)]
resumed = [('read', {'path': FIRST['path']}), ('write', FIRST), ('write', SECOND),
           ('update_plan', {'steps': [{**step, 'status': 'completed'}]})]
hold = threading.Event()
ready_to_interrupt = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.path == '/v1/chat/completions'
        assert self.headers['Authorization'] == 'Bearer local-recovery-fixture'
        messages = json.dumps(body['messages'])
        mode = 'recover' if recovery in messages else 'original' if body.get('tools') else 'summary'
        index = sum(record['mode'] == mode for record in requests)
        requests.append({'mode': mode, 'messages': body['messages'], 'max_tokens': body.get('max_tokens'),
                         'tool_choice': body.get('tool_choice'),
                         'tools': [tool['function']['name'] for tool in body.get('tools', [])]})
        script = original if mode == 'original' else resumed
        tool = script[index] if mode != 'summary' and index < len(script) else None
        tokens = 49000 if mode == 'original' and index == 5 else 3200
        base = dict(id='recovery-fixture', object='chat.completion.chunk', created=int(time.time()), model=MODEL)
        if tool:
            name, arguments = tool
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': f'{mode}-{index}', 'type': 'function',
                      'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
            finish = 'tool_calls'
        else:
            delta = {'role': 'assistant', 'content': 'Recovery mock is complete.' if mode == 'recover'
                     else 'The task needs one more verified output.'}
            finish = 'stop'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        try:
            if mode == 'original' and tool is None:
                ready_to_interrupt.set()
                hold.wait(25)
            for choice in [{'index': 0, 'delta': delta, 'finish_reason': None},
                           {'index': 0, 'delta': {}, 'finish_reason': finish}]:
                self.wfile.write(('data: ' + json.dumps({**base, 'choices': [choice]}) + '\n\n').encode())
            self.wfile.write(('data: ' + json.dumps({**base, 'choices': [], 'usage': {'prompt_tokens': tokens,
                              'completion_tokens': 18, 'total_tokens': tokens + 18}}) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except OSError:
            pass


class MockServer:
    config = {'model': 'Qwen3.8-27B-Uncensored-noMTP-IQ4_XS.gguf'}

    def key(self):
        return 'local-recovery-fixture'

    def status(self):
        return {'status': 'ready', 'model': MODEL}

    def request(self, uri):
        assert uri == '/slots'
        return [{'is_processing': False, 'n_ctx': 64000}]


def wait_for(root, match, timeout=25):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        root.update()
        if match():
            return
        time.sleep(.02)
    raise RuntimeError(f'GUI wait timed out. {[(r["mode"]) for r in requests]}')


def entries(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]


def create_gui(workspace, state, **options):
    root = tk.Tk()
    root.withdraw()
    return root, App(root, MockServer(), workspace, state, recover_jobs=True, **options)


def destroy_gui(root):
    for callback in root.tk.splitlist(root.tk.call('after', 'info')):
        root.after_cancel(callback)
    root.destroy()


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    assert server.server_address[1] != 1235
    threading.Thread(target=server.serve_forever, daemon=True).start()
    prepare = backend.prepare

    def mock_prepare(state, key, **options):
        env = prepare(state, key, **options)
        backend.profile(state, f'http://127.0.0.1:{server.server_address[1]}/v1', preserve_settings=True)
        settings = state / 'profile/settings.json'
        profile = json.loads(settings.read_text(encoding='utf-8'))
        profile['compaction'] = {'enabled': True, 'reserveTokens': 16384, 'keepRecentTokens': 1}
        settings.write_text(json.dumps(profile), encoding='utf-8')
        return env

    backend.prepare = mock_prepare
    backend.hermes_active = lambda: False
    with tempfile.TemporaryDirectory(prefix='pi-job-recovery-') as tmp:
        workspace, state = Path(tmp) / 'workspace', Path(tmp) / 'state'
        workspace.mkdir()
        state.mkdir()
        (workspace / 'proof.py').write_text(f'print({TOOL_WITNESS!r})\n', encoding='utf-8')
        root, ui = create_gui(workspace, state)
        try:
            ui.prompt.insert('1.0', OBJECTIVE)
            ui.send_button.invoke()
            wait_for(root, ready_to_interrupt.is_set)
            job = ui.jobs.current()
            assert job and job['payload']['message'] == OBJECTIVE
            saved_before = entries(job['session'])
            assert sum(entry['type'] == 'compaction' for entry in saved_before) >= 1
            first = workspace / FIRST['path']
            original_timestamp = first.stat().st_mtime_ns
            assert first.read_bytes() == FIRST['content'].encode()
            original_transport = ui.rpc
            original_rpc = original_transport.process
            destroy_gui(root)
            # Construct a new normal GUI against the same state. No prompt is submitted.
            root, ui = create_gui(workspace, state, exit_after_job=True)
            close_requested = []
            ui.close = lambda: close_requested.append(Jobs(state).current() is None)
            wait_for(root, lambda: ui.status.get() == 'Waiting for the previous Pi process')
            assert ui.rpc is None and original_rpc.poll() is None
            original_rpc.kill()
            original_rpc.wait(timeout=5)
            wait_for(root, lambda: bool(ui.plan_steps))
            assert ui.plan_steps[0]['id'] == step['id'] and ui.chat_title.get().startswith(OBJECTIVE[:40])
            wait_for(root, lambda: ui.status.get() in ('Finished', 'Failed', 'Needs review'))
            assert ui.status.get() == 'Finished', ui.chat.get('1.0', 'end')
            assert ui.rpc.process.pid != original_rpc.pid
            proof = Jobs(state).checkpoint(job)
            all_entries = entries(job['session'])
            assert proof['phase'] == 'completed' and proof['recovered'] == 1 and not proof['pending']
            user_count = sum(entry.get('message', {}).get('role') == 'user' for entry in all_entries)
            assert user_count == 1
            assert first.stat().st_mtime_ns == original_timestamp
            assert first.read_bytes() == FIRST['content'].encode()
            assert (workspace / SECOND['path']).read_bytes() == SECOND['content'].encode()
            assert any('Recovery refused to repeat write' in json.dumps(request) for request in requests)
            assert Jobs(state).current() is None
            assert close_requested == [True]
            assert proof['plan']['steps'][0]['status'] == 'completed'
            summary = next(index for index, request in enumerate(requests) if request['mode'] == 'summary')
            retained_modes = {request['mode'] for request in requests[summary + 1:] if any(
                message.get('role') == 'tool' and TOOL_WITNESS in json.dumps(message.get('content'))
                for message in request['messages'])}
            assert {'original', 'recover'} <= retained_modes
            assert any(message.get('role') == 'tool' and message.get('tool_call_id') == 'recover-0' and
                       FIRST['content'].strip() in json.dumps(message.get('content'))
                       for request in requests if request['mode'] == 'recover' for message in request['messages'])
            print(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'native_qwen_requests': 0,
                              'gui_reopened': True, 'pinned_rpc': True, 'original_user_messages': user_count,
                              'waited_for_previous_rpc': True, 'saved_plan_visible_on_restore': True,
                              'compactions': sum(entry['type'] == 'compaction' for entry in all_entries),
                              'exact_tool_result_after_compaction_and_restart': True,
                              'first_resumed_read_used_the_saved_route': True,
                              'duplicate_write_refused': True, 'actual_files_match': True,
                              'background_close_after_archiving': True,
                              'checkpoint_phase': proof['phase'], 'request_modes': [r['mode'] for r in requests]}, indent=2))
        finally:
            hold.set()
            if ui.rpc:
                ui.rpc.close()
                if ui.rpc.process.poll() is None:
                    ui.rpc.process.wait(timeout=10)
            if root.winfo_exists():
                destroy_gui(root)
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
