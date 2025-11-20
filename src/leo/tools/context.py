"""Shared context for tool execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx

from leo.memory import (
    EpisodicMemoryStore,
    PreferenceStore,
    ReminderStore,
    TaskStore,
)
from leo.clients import HomeAssistantClient


@dataclass
class ToolContext:
    task_store: TaskStore | None = None
    reminder_store: ReminderStore | None = None
    preference_store: PreferenceStore | None = None
    episodic_store: EpisodicMemoryStore | None = None
    http_client: httpx.Client | None = None
    home_assistant: HomeAssistantClient | None = None

    def __post_init__(self) -> None:
        if self.task_store is None:
            self.task_store = TaskStore()
        if self.reminder_store is None:
            self.reminder_store = ReminderStore()
        if self.preference_store is None:
            self.preference_store = PreferenceStore()
        if self.episodic_store is None:
            self.episodic_store = EpisodicMemoryStore()
        if self.http_client is None:
            self.http_client = httpx.Client(timeout=15.0)
        if self.home_assistant is None:
            self.home_assistant = HomeAssistantClient()

    def close(self) -> None:
        if self.http_client:
            self.http_client.close()
        if self.home_assistant:
            self.home_assistant.close()


__all__ = ["ToolContext"]
