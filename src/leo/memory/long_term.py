"""Long-term memory store with embeddings, retrieval, and pruning."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, List, Mapping, Sequence

import numpy as np

from leo.clients import EmbeddingClient
from leo.db import Database


def _now() -> datetime:
    return datetime.utcnow()


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return _now()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return _now()


@dataclass(slots=True)
class MemoryEntry:
    id: int
    user_id: str
    owner_type: str
    content: str
    embedding: list[float]
    tags: list[str]
    importance: float
    plasticity: float
    created_at: str
    last_used_at: str
    metadata: dict[str, Any] | None = None


class LongTermMemoryStore:
    """Encapsulates LTM persistence, retrieval, and pruning."""

    def __init__(
        self,
        db: Database | None = None,
        embed_client: EmbeddingClient | None = None,
        *,
        total_cap_user: int = 500,
        total_cap_assistant: int = 500,
        per_tag_caps: Mapping[str, int] | None = None,
        decay_per_day: float = 0.01,
        similarity_merge_threshold: float = 0.95,
    ) -> None:
        self.db = db or Database()
        self.embed_client = embed_client or EmbeddingClient()
        self.total_cap_user = total_cap_user
        self.total_cap_assistant = total_cap_assistant
        self.per_tag_caps = per_tag_caps or {
            "preference": 120,
            "project": 150,
            "relationship": 100,
            "self": 80,
            "episodic": 80,
            "history": 80,
            "other": 50,
        }
        self.decay_per_day = decay_per_day
        self.similarity_merge_threshold = similarity_merge_threshold

    def embed_text(self, text: str) -> list[float]:
        return self.embed_client.embed(text)

    def add_memory(
        self,
        *,
        user_id: str,
        owner_type: str,
        content: str,
        tags: Sequence[str],
        importance: float = 0.5,
        plasticity: float = 0.5,
        metadata: Mapping[str, Any] | None = None,
        embedding: Sequence[float] | None = None,
    ) -> int:
        emb = embedding or self.embed_text(content)
        payload = json.dumps(list(emb))
        tag_json = json.dumps(list(tags))
        meta_json = json.dumps(metadata) if metadata else None
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO long_term_memories (
                    user_id, owner_type, content, embedding, tags, importance, plasticity, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    owner_type,
                    content,
                    payload,
                    tag_json,
                    float(importance),
                    float(plasticity),
                    meta_json,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_all(self, user_id: str, owner_type: str) -> list[MemoryEntry]:
        rows = self.db.query(
            """
            SELECT id, user_id, owner_type, content, embedding, tags, importance, plasticity,
                   created_at, last_used_at, metadata
            FROM long_term_memories
            WHERE user_id = ? AND owner_type = ?
            """,
            (user_id, owner_type),
        )
        return [self._row_to_entry(row) for row in rows]

    def search(
        self,
        *,
        user_id: str,
        owner_type: str,
        query_embedding: Sequence[float],
        limit: int = 8,
    ) -> list[MemoryEntry]:
        candidates = self.list_all(user_id, owner_type)
        if not candidates:
            return []
        q = np.array(query_embedding, dtype=np.float32)
        if np.linalg.norm(q) == 0:
            return []

        scored: list[tuple[MemoryEntry, float]] = []
        for entry in candidates:
            emb = np.array(entry.embedding, dtype=np.float32)
            denom = np.linalg.norm(q) * np.linalg.norm(emb)
            if denom == 0:
                continue
            sim = float(np.dot(q, emb) / denom)
            boost = 1.0 + entry.importance
            scored.append((entry, sim * boost))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        results = [pair[0] for pair in scored[:limit]]
        if results:
            self.update_last_used([m.id for m in results])
        return results

    def update_last_used(self, memory_ids: Iterable[int]) -> None:
        ids = list(memory_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE long_term_memories SET last_used_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                tuple(ids),
            )
            conn.commit()

    def decay_importance(self, *, user_id: str, owner_type: str) -> None:
        rows = self.db.query(
            """
            SELECT id, last_used_at, importance FROM long_term_memories
            WHERE user_id = ? AND owner_type = ?
            """,
            (user_id, owner_type),
        )
        now = _now()
        updates: list[tuple[float, int]] = []
        for row in rows:
            last_used = _parse_ts(row["last_used_at"])
            days = max(0.0, (now - last_used).total_seconds() / 86400.0)
            importance = float(row["importance"])
            decayed = max(0.0, importance - self.decay_per_day * days)
            if decayed != importance:
                updates.append((decayed, row["id"]))
        if updates:
            with self.db.connect() as conn:
                for importance, mem_id in updates:
                    conn.execute(
                        "UPDATE long_term_memories SET importance = ?, last_used_at=CURRENT_TIMESTAMP WHERE id = ?",
                        (importance, mem_id),
                    )
                conn.commit()

    def prune_caps(self, *, user_id: str) -> None:
        """Enforce total and per-tag caps by dropping lowest-importance entries."""

        self._prune_total(user_id, "user", self.total_cap_user)
        self._prune_total(user_id, "assistant", self.total_cap_assistant)
        for tag, cap in self.per_tag_caps.items():
            self._prune_tag(user_id, "user", tag, cap)
            self._prune_tag(user_id, "assistant", tag, cap)

    def merge_redundant(self, *, user_id: str, owner_type: str) -> None:
        """Merge highly similar memories, keeping the highest importance."""

        memories = self.list_all(user_id, owner_type)
        if len(memories) < 2:
            return
        embeddings = [np.array(m.embedding, dtype=np.float32) for m in memories]
        norms = [np.linalg.norm(e) for e in embeddings]

        to_delete: set[int] = set()
        for i, mi in enumerate(memories):
            if mi.id in to_delete:
                continue
            for j in range(i + 1, len(memories)):
                mj = memories[j]
                if mj.id in to_delete:
                    continue
                denom = norms[i] * norms[j]
                if denom == 0:
                    continue
                sim = float(np.dot(embeddings[i], embeddings[j]) / denom)
                if sim >= self.similarity_merge_threshold:
                    # Keep the higher-importance memory
                    keep, drop = (mi, mj) if mi.importance >= mj.importance else (mj, mi)
                    to_delete.add(drop.id)
                    self._log_event(user_id, owner_type, keep.id, "merged", {"dropped": drop.id, "similarity": sim})
        if to_delete:
            self._delete_ids(to_delete)

    def _prune_total(self, user_id: str, owner_type: str, cap: int) -> None:
        rows = self.db.query(
            """
            SELECT id FROM long_term_memories
            WHERE user_id = ? AND owner_type = ?
            ORDER BY importance ASC, last_used_at ASC
            """,
            (user_id, owner_type),
        )
        if len(rows) <= cap:
            return
        excess = len(rows) - cap
        to_drop = [row["id"] for row in rows[:excess]]
        self._log_event(user_id, owner_type, None, "prune_total", {"dropped": to_drop})
        self._delete_ids(to_drop)

    def _prune_tag(self, user_id: str, owner_type: str, tag: str, cap: int) -> None:
        rows = self.db.query(
            """
            SELECT id, tags FROM long_term_memories
            WHERE user_id = ? AND owner_type = ?
            ORDER BY importance ASC, last_used_at ASC
            """,
            (user_id, owner_type),
        )
        tagged = [row for row in rows if tag in (json.loads(row["tags"]) if row["tags"] else [])]
        if len(tagged) <= cap:
            return
        excess = len(tagged) - cap
        to_drop = [row["id"] for row in tagged[:excess]]
        self._log_event(user_id, owner_type, None, "prune_tag", {"tag": tag, "dropped": to_drop})
        self._delete_ids(to_drop)

    def _delete_ids(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self.db.connect() as conn:
            conn.execute(f"DELETE FROM long_term_memories WHERE id IN ({placeholders})", tuple(ids))
            conn.commit()

    def _log_event(self, user_id: str, owner_type: str, memory_id: int | None, event_type: str, payload: Mapping[str, Any] | None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_events (user_id, owner_type, memory_id, event_type, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, owner_type, memory_id, event_type, json.dumps(payload) if payload else None),
            )
            conn.commit()

    def _row_to_entry(self, row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            user_id=row["user_id"],
            owner_type=row["owner_type"],
            content=row["content"],
            embedding=json.loads(row["embedding"]) if row["embedding"] else [],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            importance=float(row["importance"]),
            plasticity=float(row["plasticity"]),
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
        )


__all__ = ["LongTermMemoryStore", "MemoryEntry"]
