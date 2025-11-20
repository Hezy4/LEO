"""Episodic memory helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from leo.db import Database


@dataclass(slots=True)
class EpisodicMemory:
    id: int
    user_id: str
    summary: str
    source: Optional[str]
    created_at: str

    @classmethod
    def from_row(cls, row) -> "EpisodicMemory":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            summary=row["summary"],
            source=row["source"],
            created_at=row["created_at"],
        )


class EpisodicMemoryStore:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def record(self, user_id: str, summary: str, source: str | None = None) -> EpisodicMemory:
        memory_id = self.db.execute(
            """
            INSERT INTO episodic_memories (user_id, summary, source)
            VALUES (?, ?, ?)
            """,
            (user_id, summary, source),
        )
        return self.get(memory_id)

    def get(self, memory_id: int) -> EpisodicMemory:
        rows = self.db.query("SELECT * FROM episodic_memories WHERE id = ?", (memory_id,))
        if not rows:
            raise ValueError(f"Memory {memory_id} not found")
        return EpisodicMemory.from_row(rows[0])

    def list_recent(self, user_id: str, limit: int = 20) -> List[EpisodicMemory]:
        rows = self.db.query(
            """
            SELECT * FROM episodic_memories
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [EpisodicMemory.from_row(row) for row in rows]


__all__ = ["EpisodicMemory", "EpisodicMemoryStore"]
