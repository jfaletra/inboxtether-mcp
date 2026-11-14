"""Explicit opt-in: add the protected calendar hook to the public email factory.

The private production email launcher/adapters are deliberately not imported.
Use this entry point only behind the installation's existing owner-authenticated
MCP connection. It creates no authentication service or additional transport.
"""
from pathlib import Path
import sys


def create_server():
    # -I omits adjacent modules. Use only this operator-installed source directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from server import create_server as create_email_server
    from calendar_read_extension import register

    app = create_email_server()
    register(app)
    return app


if __name__ == '__main__':
    create_server().run(transport='stdio')
