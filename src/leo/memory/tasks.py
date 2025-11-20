"""Task storage helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from leo.db import Database


@dataclass(slots=True)
class Task:
    id: int
    user_id: str
    title: str
    description: Optional[str]
    status: str
    due_at: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "Task":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            due_at=row["due_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class TaskStore:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def create(self, user_id: str, title: str, description: str | None = None, due_at: str | None = None) -> Task:
        task_id = self.db.execute(
            """
            INSERT INTO tasks (user_id, title, description, due_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, title, description, due_at),
        )
        return self.get(task_id)

    def get(self, task_id: int) -> Task:
        rows = self.db.query("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not rows:
            raise ValueError(f"Task {task_id} not found")
        return Task.from_row(rows[0])

    def list(self, user_id: str, status: str | None = None, limit: int = 50) -> List[Task]:
        sql = "SELECT * FROM tasks WHERE user_id = ?"
        params: list = [user_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.query(sql, params)
        return [Task.from_row(row) for row in rows]

    def update_status(self, task_id: int, status: str) -> None:
        with self.db.connect() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, task_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Task {task_id} not found")


__all__ = ["Task", "TaskStore"]
