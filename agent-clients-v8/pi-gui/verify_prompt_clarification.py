"""Exercise the real desktop, pinned RPC, and a durable clarification with a local scripted provider."""
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


PROMPT = 'Prepare a short flyer. The audience and length are open.'
QUESTIONS = [
    {'question': 'Who should read the flyer?', 'choices': ['Families (default recommendation)', 'Teachers', 'Visitors']},
    {'question': 'How long should the flyer be?', 'choices': ['One page', 'Two pages', 'A postcard']},
]
TYPED = 'Four short paragraphs for caregivers'
KEY = 'local-clarification-fixture'


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        assert self.path == '/v1/chat/completions' and self.headers['Authorization'] == 'Bearer ' + KEY
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        index = len(self.server.requests)
        self.server.requests.append(body)
        calls = [
            ('prepare_prompt', {'brief': PROMPT, 'checks': ['Use both audience and length'], 'questions': QUESTIONS}),
            ('find_skills', {'query': 'general-task'}),
            ('use_skill', {'name': 'general-task', 'reason': 'Use the saved clarification.'}),
        ]
        response = {'role': 'assistant', 'content': 'Clarification complete.'}
        finish = 'stop'
        if index < len(calls):
            name, args = calls[index]
            assert name in {tool['function']['name'] for tool in body['tools']}
            response = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': f'clarify-{index}', 'type': 'function',
                        'function': {'name': name, 'arguments': json.dumps(args)}}]}
            finish = 'tool_calls'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        base = {'id': 'pi-clarify-fixture', 'object': 'chat.completion.chunk', 'model': backend.MODEL,
                'created': int(time.time())}
        for delta, reason in ((response, None), ({}, finish)):
            frame = {**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': reason}]}
            self.wfile.write(('data: ' + json.dumps(frame) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


class MockModel:
    config = {'model': 'Qwen3.8-27B-Uncensored-noMTP-IQ4_XS.gguf'}

    def status(self):
        return {'status': 'ready', 'model': backend.MODEL}

    def key(self):
        return KEY

    def request(self, path):
        assert path == '/slots'
        return [{'is_processing': False, 'n_ctx': 64000}]


def wait_for(root, condition, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if condition():
            return
        time.sleep(.02)
    raise TimeoutError('The expected clarification state did not appear.')


with ThreadingHTTPServer(('127.0.0.1', 0), Provider) as provider, tempfile.TemporaryDirectory(prefix='pi-clarification-') as folder:
    provider.requests = []
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    prepare = backend.prepare

    def mock_prepare(state, key, **options):
        env = prepare(state, key, **options)
        backend.profile(state, f'http://127.0.0.1:{provider.server_port}/v1', preserve_settings=True)
        return env

    backend.prepare = mock_prepare
    backend.hermes_active = lambda: False
    base = Path(folder)
    workspace, state = base / 'workspace', base / 'state'
    workspace.mkdir()
    state.mkdir()
    root = tk.Tk()
    root.withdraw()
    ui = App(root, MockModel(), workspace, state, recover_jobs=True)
    try:
        ui.prompt.insert('1.0', PROMPT)
        ui.send_button.invoke()
        wait_for(root, lambda: ui.clarification is not None)
        first_id, card = ui.clarification
        assert len(provider.requests) == 1 and ui.status.get() == 'Waiting for your answer'
        assert len(card.choices) == 3 and card.choices[0].cget('text') == 'Families (Recommended)'
        assert card.button.instate(('disabled',))
        assert not any(item['expanded'] for item in ui.tool_cards.values())
        job = ui.job
        saved = ui.jobs.directory / (job['id'] + '.clarification.json')
        assert read_json(saved)['questions'] == QUESTIONS and not read_json(saved)['answers']
        first_rpc = ui.rpc.process
        first_rpc.kill()
        first_rpc.wait(timeout=5)
        wait_for(root, lambda: ui.clarification and ui.clarification[0] != first_id)
        assert len(provider.requests) == 1 and ui.job['id'] == job['id']
        recovered_id, card = ui.clarification
        card.choices[0].invoke()
        wait_for(root, lambda: ui.clarification and ui.clarification[0] != recovered_id)
        assert read_json(saved)['answers'] == [{'choice': 0}]
        _, card = ui.clarification
        second_rpc = ui.rpc
        send = second_rpc.send

        def interrupt_before_delivery(action, **fields):
            if action == 'extension_ui_response' and fields.get('value') == 'saved':
                second_rpc.process.kill()
                return fields['id']
            return send(action, **fields)

        second_rpc.send = interrupt_before_delivery
        card.answer.set(TYPED)
        card.button.invoke()
        wait_for(root, lambda: ui.rpc is not second_rpc)
        assert read_json(saved)['answers'] == [{'choice': 0}, {'text': TYPED}]
        wait_for(root, lambda: not ui.active and ui.status.get() in ('Finished', 'Failed', 'Needs review'))
        assert ui.status.get() == 'Finished', ui.chat.get('1.0', 'end')
        assert ui.clarification is None and len(provider.requests) == 4
        assert read_json(saved)['answers'] == [{'choice': 0}, {'text': TYPED}]
        resumed = [message for message in provider.requests[1]['messages'] if message['role'] == 'user']
        assert resumed and 'Families' in str(resumed[-1]['content']) and TYPED in str(resumed[-1]['content'])
        entries = [json.loads(line) for line in Path(job['session']).read_bytes().splitlines()]
        assert sum(e.get('message', {}).get('role') == 'user' for e in entries) == 1
        assert sum(e.get('customType') == 'gui-skill' and e.get('data', {}).get('skillEvent') == 'brief' for e in entries) == 1
        outcome = read_json(ui.jobs.directory / (job['id'] + '.outcome.json'))
        assert outcome['reason'] == 'completed' and ui.jobs.current() is None
        print(json.dumps({'choice_count': 3, 'questions': 2, 'default_selected': False,
                          'same_pending_question_after_rpc_interruption': True, 'one_click_then_custom_saved_once': True,
                          'committed_answer_survives_interruption_before_rpc_ack': True,
                          'accepted_original_prompt_count': 1, 'clarification_reached_provider': True, 'native_inference_requests': 0}))
    finally:
        if ui.rpc and ui.rpc.process.poll() is None:
            ui.rpc.close()
            ui.rpc.process.wait(timeout=8)
        root.destroy()
        provider.shutdown()
