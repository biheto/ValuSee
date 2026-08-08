from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


class ConnectionAdapter:
    def __init__(self, connection: Any, backend: str):
        self._connection = connection
        self.backend = backend

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
        if self.backend == "postgresql":
            sql = sql.replace("?", "%s")
        return self._connection.execute(sql, params)

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


def connect_database(sqlite_path: str | Path) -> ConnectionAdapter:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url.startswith(("postgresql://", "postgres://")):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL mode requires psycopg[binary]") from exc
        connection = psycopg.connect(database_url, row_factory=dict_row)
        return ConnectionAdapter(connection, "postgresql")

    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    return ConnectionAdapter(connection, "sqlite")


def is_integrity_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    return exc.__class__.__module__.startswith("psycopg") and exc.__class__.__name__ in {
        "IntegrityError",
        "UniqueViolation",
    }


def database_health() -> dict[str, str]:
    connection = connect_database("data/valuesee.db")
    try:
        connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "backend": connection.backend}
    finally:
        connection.close()
