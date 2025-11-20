"""Demonstrate executing tools via the registry."""
from __future__ import annotations

from leo.tools import ToolRegistry


def main() -> None:
    registry = ToolRegistry.default()

    create_result = registry.execute(
        "tasks.create",
        {
            "user_id": "henry",
            "title": "Draft orchestrator plan",
            "description": "Outline modules and tool usage",
        },
    )
    print("Created task:", create_result.data)

    list_result = registry.execute(
        "tasks.list",
        {
            "user_id": "henry",
            "limit": 5,
        },
    )
    print("Task list count:", list_result.data["count"])

    reminder_result = registry.execute(
        "reminders.create",
        {
            "user_id": "henry",
            "text": "Check orchestrator wiring",
            "remind_at": "2025-11-21T10:00:00",
        },
    )
    print("Reminder scheduled:", reminder_result.data)

    email_result = registry.execute(
        "email.send",
        {
            "user_id": "henry",
            "to": "henry@example.com",
            "subject": "Tool status",
            "body": "All systems are operating within normal parameters.",
        },
    )
    print("Email staged at:", email_result.data["outbox_file"])

    web_result = registry.execute(
        "web.search",
        {
            "query": "local AI assistant architecture",
            "max_results": 2,
        },
    )
    print("Web search sample:", web_result.data["results"][0])

    lights_result = registry.execute(
        "homeassistant.set_lights",
        {
            "room": "living room",
            "brightness": 35,
        },
    )
    print("Set lights response:", lights_result.data)

    scene_result = registry.execute(
        "homeassistant.run_scene",
        {"scene_id": "scene.relax"},
    )
    print("Run scene response:", scene_result.data)


if __name__ == "__main__":
    main()
