"""Prompt construction helpers for the orchestrator."""
from __future__ import annotations

from typing import Dict, List, Sequence

TOOL_PROTOCOL = (
    "If a tool is required, respond with JSON ONLY using the schema\n"
    "{\"tool\": \"tool.name\", \"arguments\": { ... }}.\n"
    "Do not add prose around the JSON. If no tool is needed, reply in natural language."
)


def format_persona(persona: Dict[str, object]) -> str:
    if not persona:
        return ""
    lines = ["Persona directives:"]
    for key, value in persona.items():
        pretty_value = value
        if isinstance(value, list):
            pretty_value = ", ".join(str(item) for item in value)
        lines.append(f"- {key.replace('_', ' ').title()}: {pretty_value}")
    return "\n".join(lines)


def describe_tools(tool_specs: List[Dict[str, object]]) -> str:
    if not tool_specs:
        return "No external tools are currently available."
    lines = ["Available tools:"]
    for spec in tool_specs:
        lines.append(f"- {spec['name']}: {spec['description']}")
    lines.append(TOOL_PROTOCOL)
    return "\n".join(lines)


def build_style_rules(persona: Dict[str, object]) -> str:
    rules: List[str] = []
    voice = persona.get("voice")
    default_tone = persona.get("default_tone")
    humor = persona.get("humor_style")
    pacing = persona.get("response_pacing")
    signatures = persona.get("signature_traits")
    extra_instructions = persona.get("style_instructions")
    banter_examples = persona.get("banter_examples")

    if voice:
        rules.append(f"Maintain a {voice} delivery.")
    if default_tone:
        rules.append(f"Default tone: {default_tone}.")
    if humor:
        rules.append(f"Humor style: {humor}. Favor subtle dry wit where appropriate.")
    if pacing:
        rules.append(f"Response pacing: {pacing}.")
    if signatures:
        rules.append(
            "Signature traits to surface: " + ", ".join(str(item) for item in signatures)
        )
    if extra_instructions:
        rules.extend(str(item) for item in extra_instructions)
    if banter_examples:
        rules.append("Banter references (use sparingly): " + " | ".join(banter_examples))

    if not rules:
        return ""
    lines = ["Style expectations:"]
    lines.extend(f"- {rule}" for rule in rules)
    return "\n".join(lines)


def build_memory_context(
    tasks: Sequence[object],
    reminders: Sequence[object],
    episodes: Sequence[object],
) -> str:
    sections: List[str] = []
    if tasks:
        sections.append("Open tasks:")
        for task in tasks:
            title = getattr(task, "title", "Task")
            status = getattr(task, "status", "pending")
            due_at = getattr(task, "due_at", None) or getattr(task, "due_date", "unscheduled")
            sections.append(f"- {title} (status: {status}, due: {due_at or 'unscheduled'})")
    if reminders:
        sections.append("Upcoming reminders:")
        for reminder in reminders:
            text = getattr(reminder, "text", "Reminder")
            remind_at = getattr(reminder, "remind_at", "unknown time")
            sections.append(f"- {remind_at}: {text}")
    if episodes:
        sections.append("Recent context:")
        for memory in episodes:
            summary = getattr(memory, "summary", "")
            if summary:
                sections.append(f"- {summary}")
    return "\n".join(sections)


def build_system_prompt(
    persona: Dict[str, object],
    tool_specs: List[Dict[str, object]],
    memory_context: str = "",
) -> str:
    persona_text = format_persona(persona)
    tool_text = describe_tools(tool_specs)
    style_rules = build_style_rules(persona)
    context_block = f"\n\nContext:\n{memory_context}" if memory_context else ""
    return (
        "You are LEO, a local privacy-preserving executive assistant.\n"
        "You run entirely on the user's machine and must follow their instructions.\n"
        f"{persona_text}\n\n{style_rules}\n\n{tool_text}{context_block}"
    )


__all__ = ["build_system_prompt", "build_memory_context", "build_style_rules"]
