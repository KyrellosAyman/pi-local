"""Keep a local, searchable copy of the retained Hermes qwen-local transcript text."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from typing_extensions import TypedDict


server = FastMCP('pi_history')
read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                           idempotentHint=True, openWorldHint=False)
columns = 'id, session_id, role, content, tool_name, tool_call_id, timestamp, display_kind'
identity = 'id, session_id, role, tool_name, tool_call_id, timestamp, display_kind'


class MessageIdentity(TypedDict):
    id: int
    session_id: str
    role: str
    tool_name: str | None
    tool_call_id: str | None
    timestamp: float
    display_kind: str | None


class SearchMatch(MessageIdentity):
    excerpt: str


class SearchResult(TypedDict):
    matches: list[SearchMatch]
    next_before_id: int | None


class MessagePage(MessageIdentity):
    text: str
    offset: int
    next_offset: int | None
    characters: int
    sha256: str


class MemoryPage(TypedDict):
    text: str
    path: str
    offset: int
    next_offset: int | None


def open_readonly(path):
    return sqlite3.connect(path.resolve(strict=True).as_uri() + '?mode=ro', uri=True)


def export_archive(source, destination):
    if source.resolve(strict=True) == destination.resolve():
        raise ValueError('Archive destination must differ from the source database.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, suffix='.db', delete=False) as handle:
        staged = Path(handle.name)
    try:
        with closing(open_readonly(source)) as original, closing(sqlite3.connect(staged)) as archive:
            original.execute('BEGIN')
            archive.execute('''CREATE TABLE messages (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, tool_name TEXT, tool_call_id TEXT,
                timestamp REAL NOT NULL, display_kind TEXT
            )''')
            retained = f'''SELECT {columns} FROM messages
                WHERE _compressed_summary=0 AND role IN ('user','assistant','tool')
                AND COALESCE(display_kind,'') NOT IN ('internal_notification','hidden')
                AND content IS NOT NULL AND content != '' ORDER BY id'''
            archive.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)', original.execute(retained))
            archive.commit()
            count = 0
            for actual, expected in zip(archive.execute(f'SELECT {columns} FROM messages ORDER BY id'),
                                        original.execute(retained), strict=True):
                if actual != expected:
                    raise RuntimeError(f'Archive readback differs for message {expected[0]}.')
                count += 1
        staged.replace(destination)
        return count
    finally:
        staged.unlink(missing_ok=True)


@server.tool(annotations=read_only)
def search_hermes_history(
    query: Annotated[str, Field(min_length=1, max_length=256)],
    session_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None,
    role: Annotated[str, Field(pattern='^(user|assistant|tool)$')] | None = None,
    before_id: Annotated[int, Field(gt=0)] | None = None,
    limit: Annotated[int, Field(ge=1, le=8)] = 5,
) -> SearchResult:
    """Search retained Hermes text for a literal, case-sensitive string. Use next_before_id to page older matches."""
    with closing(open_readonly(archive_path)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(f'''SELECT {identity},
            substr(content, max(1, instr(content, :query) - 60), length(:query) + 120) AS excerpt
            FROM messages WHERE instr(content, :query) > 0
            AND (:session IS NULL OR session_id = :session) AND (:role IS NULL OR role = :role)
            AND (:before IS NULL OR id < :before) ORDER BY id DESC LIMIT :take''',
            {'query': query, 'session': session_id, 'role': role,
             'before': before_id, 'take': limit + 1}).fetchall()
    return {'matches': [dict(row) for row in rows[:limit]],
            'next_before_id': rows[limit - 1]['id'] if len(rows) > limit else None}


@server.tool(annotations=read_only)
def read_hermes_message(
    session_id: Annotated[str, Field(min_length=1, max_length=256)],
    message_id: Annotated[int, Field(gt=0)],
    offset: Annotated[int, Field(ge=0)] = 0,
) -> MessagePage:
    """Read retained transcript text by exact IDs. Use next_offset to continue and compare the full text hash across pages."""
    with closing(open_readonly(archive_path)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(f'SELECT {identity}, content FROM messages WHERE session_id=? AND id=?',
                         (session_id, message_id)).fetchone()
    if row is None:
        raise ValueError('No retained message matches both IDs. Use search_hermes_history first.')
    result = dict(row)
    content = result.pop('content')
    if offset > len(content):
        raise ValueError('Offset exceeds the retained message length.')
    end = offset + 2048
    return {**result, 'text': content[offset:end], 'offset': offset,
            'next_offset': end if end < len(content) else None, 'characters': len(content),
            'sha256': sha256(content.encode('utf-8')).hexdigest()}


@server.tool(annotations=read_only)
def read_pi_memory(offset: Annotated[int, Field(ge=0, le=65536)] = 0) -> MemoryPage:
    """Read user-maintained Pi memory. Edit the returned file only if the user asked to remember or forget something."""
    path = archive_path.with_name('MEMORY.md')
    with path.open(encoding='utf-8', newline='') as stream:
        text = stream.read(65537)
    if len(text) > 65536 or offset > len(text):
        raise ValueError('Memory is beyond the 65536-character limit or the offset is invalid.')
    end = offset + 2048
    return {'text': text[offset:end], 'path': str(path), 'offset': offset,
            'next_offset': end if end < len(text) else None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--export-from', type=Path, help='Export from an existing Hermes state.db and exit.')
    args = parser.parse_args()
    archive_path = args.archive
    if args.export_from:
        print(json.dumps({'messages': export_archive(args.export_from, archive_path)}))
    else:
        archive_path = archive_path.resolve(strict=True)
        server.run(transport='stdio')
