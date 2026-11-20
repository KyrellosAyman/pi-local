"""Local MCP starter with one read-only tool and no filesystem or network access."""
from hashlib import sha256
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from typing_extensions import TypedDict

server = FastMCP('text_integrity')


class TextDigest(TypedDict):
    sha256: str
    utf8_bytes: int


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                       idempotentHint=True, openWorldHint=False))
def hash_text(text: Annotated[str, Field(max_length=4096)]) -> TextDigest:
    """Return the SHA-256 digest and UTF-8 byte count of the exact supplied text."""
    data = text.encode('utf-8')
    return {'sha256': sha256(data).hexdigest(), 'utf8_bytes': len(data)}


if __name__ == '__main__':
    server.run(transport='stdio')
