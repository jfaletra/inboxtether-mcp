"""Actual MCP client handshake; tools/list only, never an email tool invocation."""
import asyncio
import json
import sys
sys.path.insert(0, '/opt/inboxtether')
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    p = StdioServerParameters(command='/opt/inboxtether/.venv/bin/python',
                              args=['-I', '-B', '/opt/inboxtether/setup_wizard/reader_entry.py'])
    async with stdio_client(p) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(json.dumps({'tools': [t.name for t in tools.tools]}))
asyncio.run(main())
