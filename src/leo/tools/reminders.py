"""Reminder tool adapters."""
from __future__ import annotations

from typing import Any, Dict

from leo.memory import ReminderStore

from .base import BaseTool, ToolResult


class RemindersCreateTool(BaseTool):
    name = "reminders.create"
    description = "Schedule a reminder for the user at a specific timestamp."
    input_schema = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "text": {"type": "string"},
            "remind_at": {
                "type": "string",
                "description": "ISO-8601 timestamp describing when to trigger",
            },
        },
        "required": ["user_id", "text", "remind_at"],
    }

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        user_id = arguments["user_id"]
        text = arguments["text"]
        remind_at = arguments["remind_at"]

        store: ReminderStore = self.context.reminder_store  # type: ignore[assignment]
        reminder = store.create(user_id, text, remind_at)
        return ToolResult(
            success=True,
            data={
                "reminder_id": reminder.id,
                "text": reminder.text,
                "remind_at": reminder.remind_at,
            },
            message="Reminder scheduled",
        )


__all__ = ["RemindersCreateTool"]
