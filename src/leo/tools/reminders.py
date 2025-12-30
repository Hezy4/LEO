"""Reminder tool adapters."""
from __future__ import annotations

from typing import Any, Dict

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
        return ToolResult(
            success=False,
            data=None,
            message="Reminder tool is currently deprecated; no reminders were scheduled.",
        )


__all__ = ["RemindersCreateTool"]
