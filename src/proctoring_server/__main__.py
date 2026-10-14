"""Local server management; no public account-registration endpoint."""
import argparse
from urllib.parse import quote

from .service import Service, Problem
from .settings import Settings


def main():
    parser = argparse.ArgumentParser(description="Teacher service administration (server environment only)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Apply numbered SQLite migrations")
    commands.add_parser("retain", help="Purge complete evidence after its 30-day retention period")
    for name in ("invite", "reset"):
        command = commands.add_parser(name, help=f"Issue a single-use {name} link (share privately)")
        command.add_argument("--email", required=True)
    arguments = parser.parse_args()
    try:
        settings = Settings.from_env()
        service = Service(settings)
        if arguments.command == "migrate":
            print(f"Migrations applied: {settings.database.resolve()}")
        elif arguments.command == "retain":
            import json
            from .sync import SyncService
            print(json.dumps(SyncService(service).retain()))
        else:
            raw = service.issue_account_token(arguments.command, arguments.email)
            route = "invite" if arguments.command == "invite" else "reset"
            print(f"{settings.teacher_origin}/#/{route}?token={quote(raw)}")
            print(f"Single use; expires in {settings.token_seconds} seconds. Share only with the account owner.")
    except (ValueError, Problem) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
