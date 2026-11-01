"""Generate secret-free stdio guidance; never register plugins or authenticate clients."""
import json
import re
from .model import check


def connection_config(client, location, target=''):
    check(client in ('claude', 'chatgpt-desktop', 'chatgpt-web', 'other'), 'client', 'Choose a supported client option.')
    check(location in ('local', 'ssh'), 'client', 'Choose where your AI client runs.')
    command, args = '/usr/local/bin/inboxtether', []
    if location == 'ssh':
        check(type(target) is str and bool(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@+-]{0,254}', target)),
              'ssh_target', 'Enter a verified SSH alias or user@hostname, without command options.')
        command, args = 'ssh', ['-T', '-o', 'BatchMode=yes', target, '/usr/local/bin/inboxtether']
    result = {'command': command, 'args': args, 'configuration': {'mcpServers': {'inboxtether': {'command': command, 'args': args}}},
              'manual_steps': ['Your desktop must already have SSH access to this server. Verify its host key and key-based login before connecting.'] if location == 'ssh' else []}
    if client == 'claude':
        result['manual_steps'] += ['After InboxTether installation and verification succeed, download the one-time Claude connector. Run it yourself with a working Python 3 on the desktop, review the exact command and type ADD-INBOXTETHER. It preserves other entries and refuses a conflicting InboxTether entry. Restart Claude Desktop.',
                                   'First verify Python 3 works with python3 --version (macOS/Linux) or py -3 --version (Windows). A missing interpreter is a desktop prerequisite; use a working Python 3 executable, not a broken shell alias. Locate the downloaded helper first. If it is in Downloads, run from any current directory: macOS/Linux Terminal: python3 "$HOME/Downloads/connect_inboxtether_claude.py"; Windows PowerShell: py -3 "$HOME\\Downloads\\connect_inboxtether_claude.py". If the browser adds a number to the filename or it is saved elsewhere, use its actual full quoted path. Alternatively, change Terminal to the containing folder first, then run python3 ./connect_inboxtether_claude.py (Windows: py -3 .\\connect_inboxtether_claude.py).',
                                   'No manual JSON editing is needed. The Ubuntu installer does not edit your desktop files or install an extension. Server installation success does not verify the AI-client connection; check its tools after restarting the client.']
        result['documentation'] = 'https://modelcontextprotocol.io/docs/develop/connect-local-servers'
    elif client == 'chatgpt-desktop':
        result['manual_steps'] += ['In the supported ChatGPT desktop/Codex host, open Settings → MCP servers → Add server. Choose STDIO and use the command and arguments shown. Save and restart the connection.',
                                   'This local configuration does not install a hosted ChatGPT web plugin.']
        result['documentation'] = 'https://learn.chatgpt.com/docs/extend/mcp'
    elif client == 'chatgpt-web':
        result['manual_steps'] += ['ChatGPT web needs a supported hosted-plugin or Secure MCP Tunnel connection. This installer provides stdio only and creates no tunnel, plugin, key or external authentication.',
                                   'Use the documented, separately owner-configured transport if your workspace supports it, or choose a compatible stdio client. Web connection remains a manual requirement.']
        result['documentation'] = 'https://developers.openai.com/api/docs/guides/secure-mcp-tunnels'
        result['web_connection_configured'] = False
    else:
        result['manual_steps'] += ['Use the generated command and argument list in your client’s supported MCP stdio settings. Confirm the intended tools after connecting. Client-specific approval behavior must be reviewed separately.']
        result['documentation'] = 'https://modelcontextprotocol.io/docs/develop/connect-local-servers'
    return result
