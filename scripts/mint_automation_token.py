"""Bootstrap: mint an automation token (kdw_at_...) directly in a database.

Prefer the API when it is deployed: log into the admin UI and call
POST /api/admin/automation-tokens with the superadmin JWT. This script exists for the very first
token, or for a local or staging database.

The target database comes from the environment exactly like the API: TURSO_DATABASE_URL and
TURSO_AUTH_TOKEN (process env first, then api/.env and api/.env.local). The script never runs
migrations: the automation_tokens table must already exist (start the API once against that
database). A remote database (libsql://, https://, wss://) requires --yes, so a stray .env can't
point it at production by accident.

Usage (from api/):
    TURSO_DATABASE_URL=file:local.db .venv/bin/python scripts/mint_automation_token.py \\
        --owner-email you@example.com --name "daily routine" \\
        --scopes lifecycle:run,email:read,feedback:read,feedback:reply,blog:write,blog:publish,stats:read

Then store the printed token in the macOS Keychain (never in a repo, skill or workflow file):
    security add-generic-password -a "$USER" -s kodwai-automation -w '<token>'
The daily routine reads it with: security find-generic-password -s kodwai-automation -w
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.database import connect, disconnect, execute, fetch_one  # noqa: E402
from app.services.automation_tokens import (  # noqa: E402
    AUTOMATION_SCOPES,
    DEFAULT_EXPIRES_DAYS,
    mint_token,
)

REMOTE_SCHEMES = ("libsql", "https", "http", "wss", "ws")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint a kdw_at_ automation token (plaintext printed once).")
    parser.add_argument("--owner-email", required=True, help="Superadmin who owns the token (audit rows use this id).")
    parser.add_argument("--name", required=True, help="Label, e.g. 'daily routine'.")
    parser.add_argument("--scopes", required=True, help=f"Comma-separated. Allowed: {','.join(AUTOMATION_SCOPES)}")
    parser.add_argument("--expires-days", type=int, default=DEFAULT_EXPIRES_DAYS)
    parser.add_argument("--yes", action="store_true", help="Required when TURSO_DATABASE_URL is a remote database.")
    args = parser.parse_args()

    target = settings.TURSO_DATABASE_URL
    scheme = urlsplit(target).scheme.lower()
    host = urlsplit(target).hostname or target
    if scheme in REMOTE_SCHEMES and not args.yes:
        print(f"Refusing: TURSO_DATABASE_URL points at a remote database ({host}). Re-run with --yes if intended.", file=sys.stderr)
        return 2
    print(f"Target database: {host}", file=sys.stderr)

    connect()
    try:
        if fetch_one("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'automation_tokens'") is None:
            print("automation_tokens table missing: start the API once against this database to apply migrations.", file=sys.stderr)
            return 1
        owner = fetch_one("SELECT id, is_superadmin FROM users WHERE lower(email) = lower(?)", (args.owner_email,))
        if owner is None or not owner["is_superadmin"]:
            print(f"No superadmin with email {args.owner_email}.", file=sys.stderr)
            return 1
        try:
            row = mint_token(args.name, args.scopes.split(","), owner["id"], args.expires_days)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        execute(
            "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, 'create_automation_token', 'automation_token', ?, ?)",
            (secrets.token_hex(16), owner["id"], row["id"], json.dumps({
                "name": row["name"], "scopes": row["scopes"], "token_prefix": row["token_prefix"],
                "expires_at": row["expires_at"], "via": "script",
            })),
        )
    finally:
        disconnect()

    print(f"id:          {row['id']}", file=sys.stderr)
    print(f"scopes:      {','.join(row['scopes'])}", file=sys.stderr)
    print(f"expires_at:  {row['expires_at']} UTC", file=sys.stderr)
    print("token (shown once, only on stdout):", file=sys.stderr)
    print(row["token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
