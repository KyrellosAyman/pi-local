"""The two tested context allocations for the exact local Qwen installation."""
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from launcher import Launcher


NARROW = 64000
WIDE = 131072
NARROW_SHA256 = 'f917e0cde7d09b6ea9c24775972dce97f405821f47e449b24a6172733a7275fb'
WIDE_SHA256 = '8cd9389965e6769f65b210af0de6a4a2fa2a5666c5ad064e07d6f6000cca9905'
STANDALONE_NARROW_SHA256 = '52de05e5955336878935646bb62ee7ae7d24287186aa1696e1cff312637119e9'
OPTIMIZED_NARROW_SHA256 = 'f72e5d982f7059a35cf32f1d2eddab51d69f522845e69d3c89c2d6004ca2b144'
PROFILE_HASHES = {
    NARROW_SHA256: WIDE_SHA256,
    STANDALONE_NARROW_SHA256:
        'e63fc9ca51844f8b23d8e2e322d150f67f01911f293e2dbeff081a95324a6537',
    OPTIMIZED_NARROW_SHA256:
        'e63fc9ca51844f8b23d8e2e322d150f67f01911f293e2dbeff081a95324a6537',
}


def qualified_wide(config_bytes):
    digest = sha256(config_bytes).hexdigest()
    if digest == OPTIMIZED_NARROW_SHA256:
        config_bytes = Path(__file__).with_name('server-config.standard.json').read_bytes()
        digest = sha256(config_bytes).hexdigest()
        if digest != STANDALONE_NARROW_SHA256:
            raise ValueError('The original Qwen configuration differs from the qualified fallback.')
    expected_wide = PROFILE_HASHES.get(digest)
    if expected_wide is None:
        raise ValueError('The running 64k configuration differs from the qualified profile.')
    config = json.loads(config_bytes)
    flags = config['arguments']
    for name, value in (('--ctx-size', str(WIDE)), ('--n-cpu-ffn', '13'), ('--ubatch-size', '64')):
        flags[flags.index(name) + 1] = value
    wide = (json.dumps(config, indent=2) + '\n').encode()
    if sha256(wide).hexdigest() != expected_wide:
        raise RuntimeError('The generated 128k configuration differs from the qualified profile.')
    return wide


def replace_config(path, data):
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def slot_context(server):
    slots = server.request('/slots')
    if not isinstance(slots, list) or len(slots) != 1 or not isinstance(slots[0], dict):
        raise RuntimeError('The native backend did not report one model slot.')
    context = slots[0].get('n_ctx')
    if type(context) is not int or context <= 0:
        raise RuntimeError('The native backend returned an invalid context limit.')
    return context


def restart_profile(server, current, target, expected_context, verify_idle):
    """Restart the caller's owned native model while the caller holds its launcher lock."""
    path = server.directory / 'server-config.json'
    if path.read_bytes() != current:
        raise RuntimeError('The native configuration changed before the profile restart.')
    verify_idle(server)
    original_context = slot_context(server)
    server.stop()
    try:
        replace_config(path, target)
        selected = Launcher(server.directory)
        selected.start()
        verify_idle(selected)
        if slot_context(selected) != expected_context:
            raise RuntimeError('The restarted Qwen slot has a different context limit.')
        return selected
    except (OSError, RuntimeError, ValueError) as error:
        try:
            failed = Launcher(server.directory)
            if failed.owned_process() is not None:
                failed.stop()
            replace_config(path, current)
            restored = Launcher(server.directory)
            restored.start()
            verify_idle(restored)
            if slot_context(restored) != original_context:
                raise RuntimeError('The restored native slot has a different context limit.')
        except (OSError, RuntimeError, ValueError) as rollback:
            raise RuntimeError(f'Profile restart failed and the original profile could not be restored: {rollback}') from error
        raise RuntimeError(f'Profile restart failed. The original profile was restored: {error}') from error
