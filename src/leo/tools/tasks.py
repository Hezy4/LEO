"""Task-related tool adapters."""
from __future__ import annotations

from typing import Any, Dict

from leo.memory import TaskStore

from .base import BaseTool, ToolResult


class TasksCreateTool(BaseTool):
    name = "tasks.create"
    description = "Create a new task in the user's task list."
    input_schema = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "due_at": {"type": "string", "description": "ISO-8601 timestamp"},
        },
        "required": ["user_id", "title"],
    }

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        user_id = arguments["user_id"]
        title = arguments["title"]
        description = arguments.get("description")
        due_at = arguments.get("due_at") or arguments.get("due_date") or arguments.get("due")

        store: TaskStore = self.context.task_store  # type: ignore[assignment]
        task = store.create(user_id, title, description, due_at)
        return ToolResult(
            success=True,
            data={
                "task_id": task.id,
                "title": task.title,
                "status": task.status,
                "due_at": task.due_at,
            },
            message="Task created",
        )


class TasksListTool(BaseTool):
    name = "tasks.list"
    description = "List tasks for a user with an optional status filter."
    input_schema = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "status": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "required": ["user_id"],
    }

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        user_id = arguments["user_id"]
        status = arguments.get("status")
        limit = arguments.get("limit", 20)

        store: TaskStore = self.context.task_store  # type: ignore[assignment]
        tasks = store.list(user_id, status=status, limit=limit)
        payload = [
            {
                "task_id": task.id,
                "title": task.title,
                "status": task.status,
                "due_at": task.due_at,
            }
            for task in tasks
        ]
        return ToolResult(success=True, data={"tasks": payload, "count": len(payload)})


class TasksUpdateStatusTool(BaseTool):
    name = "tasks.update_status"
    description = "Update the status of an existing task (use to mark tasks as completed)."
    input_schema = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "task_id": {"type": "integer"},
            "status": {
                "type": "string",
                "description": "Desired status such as 'completed', 'pending', or 'in_progress'. Defaults to 'completed'.",
            },
        },
        "required": ["task_id"],
    }

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        task_id = arguments["task_id"]
        status = (arguments.get("status") or "completed").strip()
        if not status:
            status = "completed"

        store: TaskStore = self.context.task_store  # type: ignore[assignment]
        store.update_status(task_id, status)
        task = store.get(task_id)
        return ToolResult(
            success=True,
            data={
                "task_id": task.id,
                "title": task.title,
                "status": task.status,
                "due_at": task.due_at,
            },
            message=f"Task {task.id} marked as {task.status}.",
        )


__all__ = ["TasksCreateTool", "TasksListTool", "TasksUpdateStatusTool"]
