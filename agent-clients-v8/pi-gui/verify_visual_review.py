"""Exercise the visual review guard in the installed Pi RPC and model-facing wire."""

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Thread

from PIL import Image

import pi_backend as backend
import verify_job_recovery as fixture


def verify_rejected_checkpoint(root):
    workspace, state = root / 'workspace', root / 'state'
    workspace.mkdir()
    state.mkdir()
    for n in range(9):
        Image.new('RGB', (64, 64), (20 * n, 80, 160)).save(workspace / f'{n}.png')
    next_step = {**fixture.step, 'id': 'review', 'status': 'in_progress'}
    plan = [{**fixture.step, 'status': 'completed'}, next_step]
    omitted = ('update_plan', {'steps': [next_step], 'reason': 'Reviewed the frames. Check the repaired output.'})
    rejected = [omitted, ('update_plan', {**omitted[1], 'reason': 'x' * 301}), omitted]
    fixture.original = [*fixture.bootstrap, ('update_plan', {'steps': plan}), *fixture.bootstrap[2:],
                        *(('view_image_file', {'path': f'{n}.png'}) for n in range(9)),
                        *rejected, ('write', fixture.SECOND)]
    fixture.requests.clear()
    prepare, hermes_active = backend.prepare, backend.hermes_active
    with ThreadingHTTPServer(('127.0.0.1', 0), fixture.Handler) as server:
        Thread(target=server.serve_forever, daemon=True).start()

        def mock_prepare(state, key, **options):
            env = prepare(state, key, **options)
            backend.profile(state, f'http://127.0.0.1:{server.server_port}/v1', preserve_settings=True)
            return env

        backend.prepare = mock_prepare
        backend.hermes_active = lambda: False
        gui, ui = fixture.create_gui(workspace, state)
        try:
            ui.prompt.insert('1.0', fixture.OBJECTIVE)
            ui.send_button.invoke()
            fixture.wait_for(gui, lambda: ui.job and ui.active)
            job = ui.job
            fixture.wait_for(gui, lambda: not ui.active)
            saved = ui.jobs.checkpoint(job)
            assert saved.get('phase') == 'needs_review', saved
            assert saved['plan']['steps'] == plan, saved['plan']
            assert not saved['pending'] and ui.jobs.status(job) == 'needs_review'
            assert not (workspace / fixture.SECOND['path']).exists()
            assert len(fixture.requests) == len(fixture.original) - 1
            assert all(r['tool_choice'] == 'required' and r['tools'] == ['update_plan']
                       for r in fixture.requests[-3:])
            assert 'finish' in json.dumps(fixture.requests[-2]['messages'])
            entries = fixture.entries(job['session'])
            assert sum(e['type'] == 'message' and e['message']['role'] == 'user' for e in entries) == 1
            assert any(e.get('customType') == 'gui-stall' and e['data'].get('action') == 'pause_review'
                       for e in entries)
            count = len(fixture.requests)
            ui.rpc.close()
            ui.rpc.process.wait(timeout=15)
            fixture.destroy_gui(gui)
            gui, ui = fixture.create_gui(workspace, state)
            ui._recover_job()
            gui.update()
            assert ui.jobs.status(job) == 'needs_review' and len(fixture.requests) == count
            return {'provider_requests': count, 'forced_attempts': 3, 'checkpoint_preserved': True,
                    'later_write_absent': True, 'fresh_gui_did_not_replay': True}
        finally:
            if ui.rpc:
                ui.rpc.close()
                ui.rpc.process.wait(timeout=15)
            fixture.destroy_gui(gui)
            backend.prepare, backend.hermes_active = prepare, hermes_active
            server.shutdown()


def verify(root):
    workspace, state = root / 'workspace', root / 'state'
    workspace.mkdir()
    state.mkdir()
    for n in range(8):
        Image.new('RGB', (64, 64), (20 * n, 80, 160)).save(workspace / f'{n}.png')
    (workspace / 'alias.png').write_bytes((workspace / '0.png').read_bytes())

    def view(n):
        return 'view_image_file', {'path': f'{n}.png'}

    review = ('update_plan', {'steps': [{**fixture.step, 'status': 'in_progress'}],
                              'reason': 'Seven distinct colors were verified. Inspect the last expected color.'})
    invalid_review = ('update_plan', {**review[1], 'reason': 'x' * 301})
    fixture.original = [*fixture.bootstrap, *map(view, (0, 'alias', 1, 2, 3, 4, 5, 6)),
                        view(7), invalid_review, review, view(7)]
    fixture.hold.set()
    with ThreadingHTTPServer(('127.0.0.1', 0), fixture.Handler) as server:
        Thread(target=server.serve_forever, daemon=True).start()
        env = backend.prepare(state, fixture.MockServer().key(), workspace=workspace)
        backend.profile(state, f'http://127.0.0.1:{server.server_port}/v1', preserve_settings=True)
        events = Queue()
        rpc = backend.Rpc(workspace, env, backend.command(state), events.put)
        try:
            rpc.send('prompt', message=fixture.OBJECTIVE)
            while True:
                event = events.get(timeout=30)
                if event.get('type') == 'agent_end':
                    break
                assert event.get('type') not in ('local_exit', 'extension_error'), event
        finally:
            rpc.close()
            rpc.process.wait(timeout=15)
            server.shutdown()

    assert len(fixture.requests) == len(fixture.original) + 1
    messages = fixture.requests[-1]['messages']

    def wire_result(index):
        start, = [n for n, m in enumerate(messages) if m.get('tool_call_id') == f'original-{index}']
        end = next((n for n in range(start + 1, len(messages))
                    if messages[n]['role'] in ('assistant', 'tool')), len(messages))
        return messages[start:end]

    def has_pixels(message):
        return 'data:image/' in json.dumps(message)

    first, duplicate = wire_result(4), wire_result(5)
    checkpoint = wire_result(11)
    paused, invalid, resumed = wire_result(12), wire_result(13), wire_result(15)
    assert has_pixels(first), first
    assert 'matches an earlier view' in json.dumps(duplicate) and not has_pixels(duplicate)
    assert has_pixels(checkpoint) and 'specific change or comparison' in json.dumps(checkpoint)
    assert 'update_plan' in json.dumps(paused) and not has_pixels(paused)
    assert '300 characters' in json.dumps(invalid) and not has_pixels(invalid)
    assert has_pixels(resumed), resumed
    for i in (13, 14):
        assert fixture.requests[i]['tool_choice'] == 'required', 'Native Qwen requires string tool_choice'
        assert fixture.requests[i]['tools'] == ['update_plan']
    for i in (12, 15):
        assert fixture.requests[i]['tool_choice'] in (None, 'auto')
        assert 'view_image_file' in fixture.requests[i]['tools']
    return {'pinned_pi_rpc': True, 'native_qwen_requests': 0, 'provider_requests': len(fixture.requests),
            'duplicate_image_omitted_on_wire': True, 'checkpoint_pixels_preserved': True,
            'unchecked_ninth_view_blocked': True, 'checkpoint_forced_until_valid': True,
            'new_view_after_plan_update': True}


if __name__ == '__main__':
    with TemporaryDirectory(prefix='pi-visual-review-') as folder:
        print(json.dumps(verify(Path(folder))))
    with TemporaryDirectory(prefix='pi-visual-review-loop-') as folder:
        print(json.dumps(verify_rejected_checkpoint(Path(folder))))
