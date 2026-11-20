"""Exercise the archive export and its real local MCP transport in an isolated folder."""
import asyncio
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pi_history_mcp import export_archive


async def verify(root):
    original = root / 'original.db'
    archive = root / 'archive.db'
    needle = 'literal_%'
    long_text = 'π' * 2150 + needle + '🗺' * 2150
    with closing(sqlite3.connect(original)) as db:
        db.execute('''CREATE TABLE messages (id INTEGER, session_id TEXT, role TEXT, content TEXT,
            tool_name TEXT, tool_call_id TEXT, timestamp REAL, display_kind TEXT, _compressed_summary INTEGER)''')
        db.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)', [
            (1, 'A', 'user', needle, None, None, 1.0, None, 0),
            (2, 'A', 'tool', long_text, 'file', 'call-2', 2.0, None, 0),
            (3, 'B', 'assistant', needle, None, None, 3.0, None, 0),
            (4, 'A', 'user', needle, None, None, 4.0, None, 1),
            (5, 'A', 'user', needle, None, None, 5.0, 'internal_notification', 0),
        ])
        db.commit()
    original_hash = sha256(original.read_bytes()).digest()
    assert export_archive(original, archive) == 3
    assert sha256(original.read_bytes()).digest() == original_hash
    original.rename(root / 'legacy-profile-unavailable.db')
    memory = 'Use the source clock before editing. 🗺\n'
    (root / 'MEMORY.md').write_bytes(memory.encode())
    script = Path(__file__).with_name('pi_history_mcp.py').resolve()
    async with stdio_client(StdioServerParameters(command=sys.executable, args=['-B', str(script), str(archive)])) as (incoming, outgoing):
        async with ClientSession(incoming, outgoing) as client:
            await client.initialize()
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {'search_hermes_history', 'read_hermes_message', 'read_pi_memory'}
            assert all(tool.annotations.readOnlyHint for tool in tools)

            async def call(name, inputs):
                result = await client.call_tool(name, inputs)
                assert not result.isError
                return result.structuredContent

            first = await call('search_hermes_history', {'query': needle, 'session_id': 'A', 'limit': 1})
            assert first['matches'][0]['id'] == 2 and needle in first['matches'][0]['excerpt']
            older = await call('search_hermes_history', {'query': needle, 'before_id': first['next_before_id']})
            assert [row['id'] for row in older['matches']] == [1] and older['next_before_id'] is None
            wrong_case = await call('search_hermes_history', {'query': needle.upper()})
            assert wrong_case['matches'] == []
            remembered = await call('read_pi_memory', {})
            assert remembered['text'] == memory and remembered['next_offset'] is None
            assert Path(remembered['path']).read_bytes() == memory.encode()
            chunks = []
            offset = 0
            while offset is not None:
                part = await call('read_hermes_message', {'session_id': 'A', 'message_id': 2, 'offset': offset})
                assert part['tool_call_id'] == 'call-2' and len(part['text']) <= 2048
                assert part['sha256'] == sha256(long_text.encode()).hexdigest()
                chunks.append(part['text'])
                offset = part['next_offset']
            assert ''.join(chunks) == long_text and len(chunks) == 3
            for inputs in ({'session_id': 'B', 'message_id': 2},
                           {'session_id': 'A', 'message_id': 2, 'offset': -1}):
                assert (await client.call_tool('read_hermes_message', inputs)).isError
    return {'exported': 3, 'transport': 'stdio', 'legacy_source_unavailable_during_retrieval': True,
            'exact_unicode_pages': len(chunks), 'literal_search_and_negative_controls': True,
            'durable_memory_read_by_fresh_process': True}


if __name__ == '__main__':
    if sys.flags.optimize:
        raise RuntimeError('Run without -O so the verification assertions execute.')
    with TemporaryDirectory(prefix='pi-history-') as folder:
        print(json.dumps(asyncio.run(verify(Path(folder)))))
