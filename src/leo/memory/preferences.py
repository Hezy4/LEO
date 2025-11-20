"""Preference store utilities."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

from leo.db import Database


@dataclass(slots=True)
class PreferenceEntry:
    user_id: str
    key: str
    value: str
    updated_at: str


class PreferenceStore:
    """Encapsulates CRUD operations for the preferences table."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def upsert(self, user_id: str, key: str, value: str) -> None:
        self.db.execute(
            """
            INSERT INTO preferences (user_id, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value,
                updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, key, value),
        )

    def get_all(self, user_id: str) -> dict[str, PreferenceEntry]:
        rows = self.db.query(
            "SELECT user_id, key, value, updated_at FROM preferences WHERE user_id = ?",
            (user_id,),
        )
        return {
            row["key"]: PreferenceEntry(
                user_id=row["user_id"],
                key=row["key"],
                value=row["value"],
                updated_at=row["updated_at"],
            )
            for row in rows
        }

    def get_persona(self, user_id: str) -> dict[str, Any]:
        """Return persona settings as nested dict (based on persona.* keys)."""

        entries = self.get_all(user_id)
        persona_entries = {
            key.removeprefix("persona."): entry.value
            for key, entry in entries.items()
            if key.startswith("persona.")
        }
        nested: Dict[str, Any] = {}
        for key, value in persona_entries.items():
            self._assign_nested(nested, key.split("."), self._coerce(value))
        return nested

    def _assign_nested(self, acc: Dict[str, Any], parts: list[str], value: Any) -> None:
        cursor = acc
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value

    def _coerce(self, value: str) -> Any:
        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value


__all__ = ["PreferenceStore", "PreferenceEntry"]
