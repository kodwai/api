from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import libsql_experimental as libsql

from app.core.config import settings

logger = logging.getLogger(__name__)

_connection: libsql.Connection | None = None


def get_connection() -> libsql.Connection:
    """Return the active database connection. Raises if not initialized."""
    if _connection is None:
        raise RuntimeError("Database connection has not been initialized. Call connect() first.")
    return _connection


def connect() -> libsql.Connection:
    """Create and store the database connection."""
    global _connection
    _connection = libsql.connect(
        database=settings.TURSO_DATABASE_URL,
        auth_token=settings.TURSO_AUTH_TOKEN,
    )
    logger.info("Connected to Turso database")
    return _connection


def reconnect() -> libsql.Connection:
    """Force reconnect to the database (handles stale Turso streams)."""
    global _connection
    try:
        if _connection is not None:
            _connection.close()
    except Exception:
        pass
    _connection = None
    return connect()


def disconnect() -> None:
    """Close the database connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
        logger.info("Disconnected from Turso database")


def _split_sql(sql: str) -> list[str]:
    """Split SQL on semicolons that are outside of string literals."""
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_string:
            in_string = True
            current.append(ch)
        elif ch == "'" and in_string:
            # Check for escaped quote ('')
            if i + 1 < len(sql) and sql[i + 1] == "'":
                current.append("''")
                i += 1
            else:
                in_string = False
                current.append(ch)
        elif ch == ";" and not in_string:
            statements.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        statements.append("".join(current))
    return statements


def run_migrations() -> None:
    """Execute all SQL migration files in order, skipping already-applied ones."""
    conn = get_connection()
    migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations"
    if not migrations_dir.exists():
        logger.warning("No migrations directory found at %s", migrations_dir)
        return

    # Create migrations tracking table if it doesn't exist
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()

    # Get already-applied migrations
    cursor = conn.execute("SELECT name FROM _migrations")
    applied = {row[0] for row in cursor.fetchall()}

    migration_files = sorted(migrations_dir.glob("*.sql"))
    for migration_file in migration_files:
        if migration_file.name in applied:
            logger.info("Skipping already-applied migration: %s", migration_file.name)
            continue

        logger.info("Running migration: %s", migration_file.name)
        sql = migration_file.read_text()
        # Split on semicolons that are NOT inside string literals
        statements = _split_sql(sql)
        for statement in statements:
            # Strip comment-only lines
            lines = [line for line in statement.strip().splitlines() if line.strip() and not line.strip().startswith("--")]
            cleaned = "\n".join(lines).strip()
            if cleaned:
                conn.execute(cleaned)
        conn.execute("INSERT INTO _migrations (name) VALUES (?)", (migration_file.name,))
        conn.commit()
        logger.info("Applied migration: %s", migration_file.name)

    logger.info("All migrations applied successfully")


def get_db() -> libsql.Connection:
    """Dependency that returns the active database connection."""
    return get_connection()


def _execute_with_retry(fn, *args, **kwargs):
    """Execute a DB function, reconnecting once on stream errors."""
    try:
        return fn(*args, **kwargs)
    except (ValueError, Exception) as e:
        if "stream not found" in str(e) or "stream" in str(e).lower():
            logger.warning("Turso stream error, reconnecting: %s", e)
            reconnect()
            return fn(*args, **kwargs)
        raise


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Execute a query and return a single row as a dict, or None."""
    def _run():
        conn = get_connection()
        cursor = conn.execute(query, params)
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))
    return _execute_with_retry(_run)


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Execute a query and return all rows as dicts."""
    def _run():
        conn = get_connection()
        cursor = conn.execute(query, params)
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    return _execute_with_retry(_run)


def execute(query: str, params: tuple[Any, ...] = ()) -> None:
    """Execute a write query and commit."""
    def _run():
        conn = get_connection()
        conn.execute(query, params)
        conn.commit()
    _execute_with_retry(_run)
