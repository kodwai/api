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


def disconnect() -> None:
    """Close the database connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
        logger.info("Disconnected from Turso database")


def run_migrations() -> None:
    """Execute all SQL migration files in order."""
    conn = get_connection()
    migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations"
    if not migrations_dir.exists():
        logger.warning("No migrations directory found at %s", migrations_dir)
        return

    migration_files = sorted(migrations_dir.glob("*.sql"))
    for migration_file in migration_files:
        logger.info("Running migration: %s", migration_file.name)
        sql = migration_file.read_text()
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(statement)
        conn.commit()
    logger.info("All migrations applied successfully")


def get_db() -> libsql.Connection:
    """Dependency that returns the active database connection."""
    return get_connection()


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Execute a query and return a single row as a dict, or None."""
    conn = get_connection()
    cursor = conn.execute(query, params)
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [description[0] for description in cursor.description]
    return dict(zip(columns, row))


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Execute a query and return all rows as dicts."""
    conn = get_connection()
    cursor = conn.execute(query, params)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def execute(query: str, params: tuple[Any, ...] = ()) -> None:
    """Execute a write query and commit."""
    conn = get_connection()
    conn.execute(query, params)
    conn.commit()
