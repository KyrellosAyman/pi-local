"""Exercise exact source endings and completion on the actual Pi RPC."""

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Thread

import pi_backend as backend
import verify_job_recovery as fixture


def verify(root, *, close_at_threshold=False):
    workspace, state = root / 'workspace', root / 'state'
    workspace.mkdir()
    state.mkdir()
    first = 'Original source opening: 531942'
    middle = 'Middle present only in the full reader: 684207'
    footer = 'Exact source footer: KΩ73-測-🗺-197429'
    whole = '\n'.join((first, 'beginning rows\n' * 190, middle, 'ending rows\n' * 190, footer, ''))
    (workspace / 'record.txt').write_bytes(whole.encode())
    (workspace / 'short.txt').write_text('Short source footer: 8745', encoding='utf-8')
    fixture.requests.clear()
    reads = [('read', {'path': 'record.txt'})]
    if not close_at_threshold:
        reads.append(('read', {'path': 'short.txt'}))
    fixture.original = [*fixture.bootstrap, *reads, ('update_plan', {'steps': [{**fixture.step, 'status': 'completed'}]})]
    fixture.hold.set()
    with ThreadingHTTPServer(('127.0.0.1', 0), fixture.Handler) as server:
        Thread(target=server.serve_forever, daemon=True).start()
        env = backend.prepare(state, fixture.MockServer().key(), workspace=workspace)
        backend.profile(state, f'http://127.0.0.1:{server.server_port}/v1', preserve_settings=True)
        settings = state / 'profile/settings.json'
        profile = json.loads(settings.read_bytes())
        profile['compaction'] = {'enabled': True, 'reserveTokens': 16384, 'keepRecentTokens': 1}
        settings.write_text(json.dumps(profile), encoding='utf-8')
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

    rendered = [(r['mode'], json.dumps(r['messages'], ensure_ascii=False)) for r in fixture.requests]
    assert any(first in body and middle in body and footer in body for mode, body in rendered if mode == 'original')
    summaries = [body for mode, body in rendered if mode == 'summary']
    if close_at_threshold:
        assert not summaries
        assert len(fixture.requests) == len(fixture.original) + 1
        assert fixture.requests[-1]['tools'] == ['update_plan']
        assert all(marker in rendered[-1][1] for marker in (first, middle, footer))
        assert (workspace / 'record.txt').read_bytes() == whole.encode()
        return {'real_pinned_rpc': True, 'native_Qwen_requests': 0, 'summary_requests': 0,
                'verified_final_request_with_all_original_source_text': True}
    assert any(first in body and footer in body and middle not in body for body in summaries)
    added = [body.split('Exact prior read endings', 1)[1] for body in summaries if 'Exact prior read endings' in body]
    assert len(added) == 1 and 'record.txt' in added[0] and 'short.txt' not in added[0]
    assert all('Exact prior read endings' not in body for mode, body in rendered if mode == 'original')
    assert (workspace / 'record.txt').read_bytes() == whole.encode()
    return {'real_pinned_rpc': True, 'native_Qwen_requests': 0, 'summary_requests': len(summaries),
            'first_and_last_source_text_on_summary_wire': True, 'original_full_read_unchanged': True}


if __name__ == '__main__':
    with TemporaryDirectory(prefix='pi-compaction-read-tails-') as folder:
        print(json.dumps(verify(Path(folder))))
    with TemporaryDirectory(prefix='pi-compaction-after-plan-') as folder:
        print(json.dumps(verify(Path(folder), close_at_threshold=True)))
