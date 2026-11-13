"""Calendar-only stdio worker for an ingress that enforces owner access."""
import os

from sogo_calendar import register


def create_server():
    from mcp.server.fastmcp import FastMCP

    app = FastMCP(
        'InboxTether Owner Calendar',
        instructions=(
            'Show the complete proposal and ask for conversational approval before committing. '
            'The server authorizes the connection and cannot verify conversational approval. '
            'After an uncertain write use calendar_reconcile_operation. Do not start a replacement operation.'
        ),
    )
    configured = os.environ.get('INBOXTETHER_CALDAV_ACCOUNTS')
    if configured is None:
        register(app, owner_connection=True, legacy_writes=False)
    else:
        from calendar_accounts import CalendarAccounts
        from calendar_owner_operations import register_owner_operations

        accounts = CalendarAccounts(configured)
        register(app, accounts=accounts)
        register_owner_operations(app, accounts)
    return app


if __name__ == '__main__':
    create_server().run(transport='stdio')
