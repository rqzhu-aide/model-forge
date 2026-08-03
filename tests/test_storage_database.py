from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from method_hub.storage import Database, Migration


MIGRATIONS = (
    Migration(
        1,
        (
            "CREATE TABLE parent (id INTEGER PRIMARY KEY)",
            "CREATE TABLE child ("
            "id INTEGER PRIMARY KEY, "
            "parent_id INTEGER NOT NULL REFERENCES parent(id)"
            ")",
        ),
        name="initial relational schema",
    ),
    Migration(
        2,
        (
            "CREATE TABLE entries ("
            "id INTEGER PRIMARY KEY, "
            "value TEXT NOT NULL"
            ")",
        ),
        name="entries",
    ),
)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "control.sqlite3", migrations=MIGRATIONS)
    assert database.initialize() == 2
    return database


def test_initialize_is_versioned_and_idempotent(database: Database) -> None:
    assert database.schema_version() == 2
    assert database.initialize() == 2

    with database.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {"parent", "child", "entries"} <= names


def test_connections_enable_wal_and_foreign_keys(database: Database) -> None:
    with database.connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert foreign_keys == 1


def test_transaction_rolls_back_on_exception(database: Database) -> None:
    with pytest.raises(RuntimeError, match="abort transaction"):
        with database.transaction() as connection:
            connection.execute("INSERT INTO entries(value) VALUES (?)", ("draft",))
            raise RuntimeError("abort transaction")

    with database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    assert count == 0


def test_foreign_key_enforcement_is_active_inside_transactions(
    database: Database,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO child(id, parent_id) VALUES (?, ?)",
                (1, 999),
            )


def test_immediate_transaction_takes_the_sqlite_write_reservation(
    database: Database,
) -> None:
    competing: sqlite3.Connection | None = None
    try:
        with database.immediate_transaction():
            competing = sqlite3.connect(
                database.path,
                timeout=0,
                isolation_level=None,
            )
            competing.execute("PRAGMA busy_timeout = 0")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("BEGIN IMMEDIATE")
    finally:
        if competing is not None:
            competing.close()
