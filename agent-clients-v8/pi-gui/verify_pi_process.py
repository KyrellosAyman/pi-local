"""Verify scoped script launch and process results over local MCP stdio."""
import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify(root):
    workspace, other = root / 'workspace', root / 'other'
    workspace.mkdir()
    other.mkdir()
    (workspace / 'probe.py').write_text('import sys\nprint("x" * 4200 + sys.argv[1])\n'
                                        'print("recorded error", file=sys.stderr)\nraise SystemExit(7)\n', encoding='utf-8')
    (workspace / 'probe.ps1').write_text('Write-Output "powershell completed"\n', encoding='ascii')
    (other / 'outside.py').write_text('raise SystemExit(0)\n', encoding='utf-8')
    server = Path(__file__).with_name('pi_process_mcp.py').resolve()

    def parameters(directory):
        return StdioServerParameters(command=sys.executable, args=['-B', str(server), '--state', str(root / 'jobs')],
                                     cwd=directory)

    async with stdio_client(parameters(workspace)) as streams, ClientSession(*streams) as session:
        await session.initialize()
        assert {t.name for t in (await session.list_tools()).tools} == {'start_workspace_script', 'poll_workspace_script'}
        outside = await session.call_tool('start_workspace_script', {'path': str(other / 'outside.py')})
        assert outside.isError

        async def run(path, args):
            start = await session.call_tool('start_workspace_script', {'path': path, 'args': args})
            assert not start.isError, start
            job = start.structuredContent['job_id']
            for _ in range(70):
                response = await session.call_tool('poll_workspace_script', {'job_id': job})
                assert not response.isError, response
                if response.structuredContent['status'] == 'exited':
                    return response.structuredContent
                await asyncio.sleep(.1)
            raise AssertionError('Expected an exact completion receipt.')

        marker = 'test argument: café " & $'
        python = await run('probe.py', [marker])
        assert python['exit_code'] == 7 and python['output_truncated'] and marker in python['stdout_tail']
        assert 'recorded error' in python['stderr_tail'] and len(python['stdout_tail'].encode()) <= 4096
        powershell = await run('probe.ps1', [])
        assert powershell['exit_code'] == 0 and 'powershell completed' in powershell['stdout_tail']
    async with stdio_client(parameters(other)) as streams, ClientSession(*streams) as session:
        await session.initialize()
        rejected = await session.call_tool('poll_workspace_script', {'job_id': python['job_id']})
        assert rejected.isError
    return {'python_nonzero_result': python['exit_code'], 'powershell_success': powershell['exit_code'] == 0,
            'exact_arguments_and_bounded_output': True, 'outside_script_rejected': True,
            'foreign_workspace_id_rejected': True}


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('Run without -O to keep the assertions active.')
    with TemporaryDirectory(prefix='pi-process-check-') as folder:
        print(json.dumps(asyncio.run(verify(Path(folder)))))
