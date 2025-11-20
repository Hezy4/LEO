"""Reminder storage helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from leo.db import Database


@dataclass(slots=True)
class Reminder:
    id: int
    user_id: str
    text: str
    remind_at: str
    created_at: str
    acknowledged_at: Optional[str]

    @classmethod
    def from_row(cls, row) -> "Reminder":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            text=row["text"],
            remind_at=row["remind_at"],
            created_at=row["created_at"],
            acknowledged_at=row["acknowledged_at"],
        )


class ReminderStore:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def create(self, user_id: str, text: str, remind_at: str) -> Reminder:
        reminder_id = self.db.execute(
            """
            INSERT INTO reminders (user_id, text, remind_at)
            VALUES (?, ?, ?)
            """,
            (user_id, text, remind_at),
        )
        return self.get(reminder_id)

    def get(self, reminder_id: int) -> Reminder:
        rows = self.db.query("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        if not rows:
            raise ValueError(f"Reminder {reminder_id} not found")
        return Reminder.from_row(rows[0])

    def list_pending(self, current_time_iso: str, user_id: str | None = None) -> List[Reminder]:
        sql = "SELECT * FROM reminders WHERE acknowledged_at IS NULL AND remind_at <= ?"
        params: list = [current_time_iso]
        if user_id:
            sql += " AND user_id = ?"
            params.append(user_id)
        sql += " ORDER BY remind_at ASC"
        rows = self.db.query(sql, params)
        return [Reminder.from_row(row) for row in rows]

    def acknowledge(self, reminder_id: int) -> None:
        with self.db.connect() as conn:
            cursor = conn.execute(
                "UPDATE reminders SET acknowledged_at = CURRENT_TIMESTAMP WHERE id = ?",
                (reminder_id,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Reminder {reminder_id} not found")


__all__ = ["Reminder", "ReminderStore"]
