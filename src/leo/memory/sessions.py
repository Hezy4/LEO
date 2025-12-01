"""Persistent conversation session storage."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict

from leo.db import Database


@dataclass(slots=True)
class ConversationMessage:
    session_id: str
    role: str
    content: str
    created_at: str


class SessionStore:
    def __init__(self, db: Database | None = None, *, max_history: int = 20, max_age_minutes: int | None = None) -> None:
        self.db = db or Database()
        self.max_history = max_history
        self.max_age_minutes = max_age_minutes

    def append(self, session_id: str, user_id: str, role: str, content: str) -> None:
        if not session_id:
            return
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO conversation_sessions (session_id, user_id) VALUES (?, ?)",
                (session_id, user_id),
            )
            conn.execute(
                "INSERT INTO conversation_messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            conn.commit()
            # Trim history if needed
            conn.execute(
                """
                DELETE FROM conversation_messages
                WHERE id IN (
                    SELECT id FROM conversation_messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (session_id, self.max_history),
            )
            conn.commit()

    def get_history(self, session_id: str, *, max_age_minutes: int | None = None) -> List[Dict[str, str]]:
        age_limit = max_age_minutes if max_age_minutes is not None else self.max_age_minutes
        if age_limit:
            rows = self.db.query(
                """
                SELECT role, content FROM conversation_messages
                WHERE session_id = ?
                  AND created_at >= datetime('now', ?)
                ORDER BY created_at ASC, id ASC
                """,
                (session_id, f"-{int(age_limit)} minutes"),
            )
        else:
            rows = self.db.query(
                """
                SELECT role, content FROM conversation_messages
                WHERE session_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (session_id,),
            )
        return [
            {"role": row["role"], "content": row["content"]}
            for row in rows
        ]

    def reset(self, session_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM conversation_sessions WHERE session_id = ?", (session_id,))
            conn.commit()


__all__ = ["SessionStore", "ConversationMessage"]
