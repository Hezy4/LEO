"""SQLite helper utilities for LEO."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

from leo.config import DatabaseConfig

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    """Simple helper around sqlite3 with schema bootstrapping."""

    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self.config = config or DatabaseConfig.from_env()
        self.path = Path(self.config.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def initialize(self, schema_path: Path | None = None) -> None:
        """Create tables if they do not exist using schema.sql."""

        script_path = schema_path or SCHEMA_PATH
        script = Path(script_path).read_text()
        with self.connect() as conn:
            conn.executescript(script)

    def execute(self, sql: str, params: Sequence | None = None) -> int:
        params = params or []
        with self.connect() as conn:
            cursor = conn.execute(sql, tuple(params))
            conn.commit()
            return cursor.lastrowid

    def query(self, sql: str, params: Sequence | None = None) -> list[sqlite3.Row]:
        params = params or []
        with self.connect() as conn:
            cursor = conn.execute(sql, tuple(params))
            rows = cursor.fetchall()
        return rows


__all__ = ["Database", "SCHEMA_PATH"]
