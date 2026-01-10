"""Interfaces for memory backends."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Mapping, Sequence


class MemoryStore(ABC):
    """Core contract for long-term memory backends."""

    @abstractmethod
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
        """Persist a memory entry and return its ID."""

    @abstractmethod
    def search(
        self,
        *,
        user_id: str,
        owner_type: str,
        query_embedding: Sequence[float],
        limit: int = 8,
    ) -> list["MemoryEntry"]:
        """Retrieve the most relevant memories for a query."""

    @abstractmethod
    def update_usage(self, memory_ids: Iterable[int]) -> None:
        """Record that the given memories were used."""

    @abstractmethod
    def run_maintenance(self, *, user_id: str) -> None:
        """Apply pruning/decay/merge policies for a user."""


__all__ = ["MemoryStore"]
