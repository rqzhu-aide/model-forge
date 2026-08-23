"""Small transactional SQLite foundation for greenfield control state."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .errors import DatabaseConfigurationError, DatabaseMigrationError


@dataclass(frozen=True, slots=True)
class Migration:
    """One ordered, transactional SQLite schema migration."""

    version: int
    statements: tuple[str, ...]
    name: str = ""

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version < 1:
            raise DatabaseMigrationError(
                "database.invalid_migration",
                "Migration versions must be positive integers.",
            )
        if not isinstance(self.statements, tuple) or not self.statements:
            raise DatabaseMigrationError(
                "database.invalid_migration",
                f"Migration {self.version} must contain a nonempty tuple of SQL statements.",
            )
        if any(type(statement) is not str or not statement.strip() for statement in self.statements):
            raise DatabaseMigrationError(
                "database.invalid_migration",
                f"Migration {self.version} contains an empty or non-text SQL statement.",
            )
        if type(self.name) is not str:
            raise DatabaseMigrationError(
                "database.invalid_migration",
                f"Migration {self.version} name must be text.",
            )


class Database:
    """Open consistently configured SQLite connections and transactions.

    Schema versions use ``PRAGMA user_version``. Calling :meth:`initialize`
    applies every pending migration inside one ``BEGIN IMMEDIATE`` transaction,
    making concurrent bootstrap attempts idempotent.
    """

    __slots__ = ("_busy_timeout_ms", "_migrations", "_path", "_timeout")

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        migrations: Sequence[Migration] = (),
        timeout: float = 5.0,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        try:
            raw = os.fspath(path)
        except TypeError as error:
            raise DatabaseConfigurationError(
                "database.invalid_path",
                "Database path must be a filesystem path.",
            ) from error
        if type(raw) is bytes or not raw or "\x00" in raw:
            raise DatabaseConfigurationError(
                "database.invalid_path",
                "Database path must be nonempty text without NUL characters.",
            )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
            raise DatabaseConfigurationError(
                "database.invalid_timeout",
                "Database timeout must be a nonnegative number.",
            )
        if type(busy_timeout_ms) is not int or busy_timeout_ms < 0:
            raise DatabaseConfigurationError(
                "database.invalid_busy_timeout",
                "Database busy timeout must be a nonnegative integer.",
            )

        candidate = Path(os.path.abspath(os.path.expanduser(raw)))
        try:
            parent = candidate.parent.resolve(strict=True)
        except OSError as error:
            raise DatabaseConfigurationError(
                "database.parent_unavailable",
                f"Database parent directory is unavailable: {candidate.parent}.",
            ) from error
        if not parent.is_dir():
            raise DatabaseConfigurationError(
                "database.parent_unavailable",
                f"Database parent is not a directory: {parent}.",
            )
        candidate = parent / candidate.name

        ordered = tuple(migrations)
        if any(not isinstance(item, Migration) for item in ordered):
            raise DatabaseMigrationError(
                "database.invalid_migration",
                "Every configured migration must be a Migration instance.",
            )
        versions = tuple(item.version for item in ordered)
        expected_versions = tuple(range(1, len(ordered) + 1))
        if versions != expected_versions:
            raise DatabaseMigrationError(
                "database.migration_gap",
                "Migration versions must be ordered and contiguous starting at 1.",
            )

        self._path = candidate
        self._migrations = ordered
        self._timeout = float(timeout)
        self._busy_timeout_ms = busy_timeout_ms
        self._validate_existing_file()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def latest_schema_version(self) -> int:
        return len(self._migrations)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield one WAL and foreign-key configured autocommit connection."""

        self._validate_existing_file()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self._path,
                timeout=self._timeout,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            self._configure(connection)
            self._validate_existing_file()
            yield connection
        finally:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Commit a unit of work, or roll it back on every escaping exception."""

        if type(immediate) is not bool:
            raise TypeError("immediate must be a boolean")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                try:
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    @contextmanager
    def immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        """Convenience context manager for ``BEGIN IMMEDIATE``."""

        with self.transaction(immediate=True) as connection:
            yield connection

    def initialize(self) -> int:
        """Bootstrap WAL mode and atomically apply every pending migration."""

        with self.immediate_transaction() as connection:
            current = _user_version(connection)
            latest = self.latest_schema_version
            if current > latest:
                raise DatabaseMigrationError(
                    "database.schema_too_new",
                    f"Database schema version {current} is newer than supported version {latest}.",
                )
            for migration in self._migrations[current:]:
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {migration.version}")
            return latest

    def schema_version(self) -> int:
        """Return the currently committed SQLite schema version."""

        with self.connect() as connection:
            return _user_version(connection)

    def _configure(self, connection: sqlite3.Connection) -> None:
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
        if foreign_keys != 1:
            raise DatabaseConfigurationError(
                "database.foreign_keys_unavailable",
                "SQLite foreign-key enforcement could not be enabled.",
            )

        mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode != "wal":
            mode = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
        if mode != "wal":
            raise DatabaseConfigurationError(
                "database.wal_unavailable",
                f"SQLite returned journal mode {mode!r} instead of WAL.",
            )
        connection.execute("PRAGMA synchronous = NORMAL")

    def _validate_existing_file(self) -> None:
        try:
            metadata = self._path.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise DatabaseConfigurationError(
                "database.path_unavailable",
                f"Database path cannot be inspected: {self._path}.",
            ) from error
        reparse_flag = getattr(
            stat,
            "FILE_ATTRIBUTE_REPARSE_POINT",
            0x400 if os.name == "nt" else 0,
        )
        is_reparse = bool(
            reparse_flag
            and getattr(metadata, "st_file_attributes", 0) & reparse_flag
        )
        if stat.S_ISLNK(metadata.st_mode) or is_reparse or not stat.S_ISREG(metadata.st_mode):
            raise DatabaseConfigurationError(
                "database.unsafe_path",
                f"Database path must be a regular file, not a link: {self._path}.",
            )


def _user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])
