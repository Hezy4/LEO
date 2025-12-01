"""FastAPI app exposing the LEO orchestrator."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from leo.clients import OllamaClient, OllamaError, EmbeddingClient
from leo.memory import (
    PreferenceStore,
    TaskStore,
    ReminderStore,
    EpisodicMemoryStore,
    SessionStore,
    PersonaStore,
    MoodStore,
    LongTermMemoryStore,
)
from leo.tools import ToolRegistry

from .prompts import build_system_prompt, build_memory_context
from .personality import (
    PERSONALITY_FILTER_ENABLED,
    classify_interaction_effect,
    select_top_traits,
    blend_personality_vector,
    combine_with_mood,
    build_personality_filter_prompt,
)

SPEECH_FRIENDLY_REMINDER = (
    "Provide the final response in plain conversational sentences suitable for text-to-speech. "
    "Stay in-character as Leo (do not call yourself an assistant), keep it natural and human. "
    "Do not use Markdown, decorative punctuation, bullet characters, or code fences—describe any lists "
    "with transitions like 'First', 'Next', and 'Finally'."
)

class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None


class Action(BaseModel):
    tool: str
    arguments: Dict[str, Any]
    status: str
    result: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    actions: List[Action] = Field(default_factory=list)


class StatusResponse(BaseModel):
    llm: str
    memory: str
    tools: str


app = FastAPI(title="LEO Orchestrator", version="0.1.0")
_ollama = OllamaClient()
_embedder = EmbeddingClient()
_preferences = PreferenceStore()
_persona_store = PersonaStore()
_moods = MoodStore(persona_store=_persona_store)
_ltm = LongTermMemoryStore(embed_client=_embedder)
_tools = ToolRegistry.default()
_tasks = TaskStore()
_reminders = ReminderStore()
_episodes = EpisodicMemoryStore()
_sessions = SessionStore(max_history=12, max_age_minutes=20)


def _strip_json_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def _parse_tool_call(content: str) -> Optional[Dict[str, Any]]:
    text = _strip_json_fences(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    if isinstance(tool, str) and isinstance(arguments, dict):
        return {"tool": tool, "arguments": arguments}
    return None


def _extract_structured_tool_call(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    message = response.get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        return None
    for entry in tool_calls:
        function = entry.get("function") or {}
        raw_arguments = function.get("arguments") or entry.get("arguments")
        if isinstance(raw_arguments, str):
            try:
                parsed_arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                continue
        else:
            parsed_arguments = raw_arguments
        if not isinstance(parsed_arguments, dict):
            continue

        if "tool" in parsed_arguments and isinstance(parsed_arguments.get("arguments"), dict):
            return {
                "tool": parsed_arguments["tool"],
                "arguments": parsed_arguments["arguments"],
            }

        name = function.get("name") or entry.get("name")
        if isinstance(name, str):
            return {"tool": name, "arguments": parsed_arguments}
    return None


def _execute_tool_call(tool_call: Dict[str, Any], *, default_user_id: str | None = None) -> Action:
    name = tool_call["tool"]
    arguments = tool_call["arguments"]
    if default_user_id and "user_id" not in arguments:
        arguments["user_id"] = default_user_id
    try:
        result = _tools.execute(name, arguments)
        status = "success" if result.success else "error"
        payload = None
        if result.data is not None:
            payload = result.data if isinstance(result.data, dict) else {"data": result.data}
        return Action(
            tool=name,
            arguments=arguments,
            status=status,
            result=payload,
            message=result.message,
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        return Action(tool=name, arguments=arguments, status="error", message=str(exc))


def _finalize_with_tool(messages: List[Dict[str, str]], action: Action) -> str:
    messages.append(
        {
            "role": "system",
            "content": f"Tool {action.tool} responded with: {json.dumps({'status': action.status, 'result': action.result, 'message': action.message})}",
        }
    )
    messages.append(
        {
            "role": "user",
            "content": (
                f"Provide the final response to the user that incorporates this tool result. "
                f"{SPEECH_FRIENDLY_REMINDER}"
            ),
        }
    )
    llm_response = _ollama.chat(messages)
    return llm_response["message"]["content"].strip()


def _chat_once_with_history(messages: List[Dict[str, str]], user_message: str) -> Dict[str, Any]:
    conversation = [*messages, {"role": "user", "content": user_message}]
    llm_response = _ollama.chat(conversation)
    return {"response": llm_response, "messages": conversation}


def _gather_context(user_id: str) -> str:
    tasks = _tasks.list(user_id, limit=5)
    now = datetime.now(timezone.utc)
    horizon = (now + timedelta(days=2)).isoformat()
    reminders = _reminders.list_pending(horizon, user_id=user_id)
    episodes = _episodes.list_recent(user_id, limit=5)
    return build_memory_context(tasks, reminders, episodes)


def _retrieve_ltm_context(user_id: str, query: str) -> tuple[str, list[Any]]:
    try:
        query_embedding = _embedder.embed(query)
    except Exception:
        return "", []

    user_mems = _ltm.search(user_id=user_id, owner_type="user", query_embedding=query_embedding, limit=6)
    assistant_mems = _ltm.search(user_id=user_id, owner_type="assistant", query_embedding=query_embedding, limit=4)
    lines: list[str] = []
    collected: list[Any] = []
    for mem in user_mems:
        collected.append(mem)
        tags = ",".join(mem.tags) if hasattr(mem, "tags") else ""
        lines.append(f"[user] {mem.content} (tags: {tags}, importance: {getattr(mem, 'importance', 0):.2f})")
    for mem in assistant_mems:
        collected.append(mem)
        tags = ",".join(mem.tags) if hasattr(mem, "tags") else ""
        lines.append(f"[assistant] {mem.content} (tags: {tags}, importance: {getattr(mem, 'importance', 0):.2f})")
    text = "\n".join(lines)
    return text, collected


def _is_structured_json(text: str) -> bool:
    candidate = text.strip()
    if not candidate.startswith(("{", "[")):
        return False
    try:
        json.loads(candidate)
        return True
    except json.JSONDecodeError:
        return False


def _apply_personality_filter(
    user_message: str,
    neutral_reply: str,
    traits,
    mood_state,
) -> str:
    if not PERSONALITY_FILTER_ENABLED:
        return neutral_reply
    if not traits or mood_state is None:
        return neutral_reply
    if _is_structured_json(neutral_reply):
        return neutral_reply

    base_vector = blend_personality_vector(traits)
    combined_vector = combine_with_mood(base_vector, mood_state.values)
    prompt_messages = build_personality_filter_prompt(
        user_message=user_message,
        neutral_response=neutral_reply,
        combined_vector=combined_vector,
        active_traits=traits,
        mood=mood_state,
    )
    try:
        result = _ollama.chat(prompt_messages)
        content = result["message"]["content"].strip()
        return content or neutral_reply
    except Exception:
        return neutral_reply


def _classify_owner_type(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["you", "leo", "assistant"]):
        return "assistant"
    return "user"


def _infer_tags(text: str) -> list[str]:
    lowered = text.lower()
    tags: list[str] = []
    if any(token in lowered for token in ["prefer", "like", "love", "favorite"]):
        tags.append("preference")
    if any(token in lowered for token in ["project", "build", "plan", "working on"]):
        tags.append("project")
    if any(token in lowered for token in ["relationship", "together", "with you", "appreciate"]):
        tags.append("relationship")
    if any(token in lowered for token in ["assistant", "leo", "you"]):
        tags.append("self")
    if not tags:
        tags.append("history")
    return tags


def _extract_memory_facts(user_message: str, assistant_reply: str) -> list[str]:
    prompt = [
        {
            "role": "system",
            "content": (
                "You extract durable facts for long-term memory. Return a JSON array of concise bullet strings, "
                "or the string NONE if nothing is worth remembering. Only include persistent preferences, facts, "
                "projects, relationship notes, or commitments. Do not include transient chit-chat."
            ),
        },
        {"role": "user", "content": f"User said: {user_message}\nAssistant replied: {assistant_reply}\nExtract memory bullets or NONE."},
    ]
    try:
        result = _ollama.chat(prompt)
        content = result["message"]["content"].strip()
        if content.lower().startswith("none"):
            return []
        if content.startswith("```"):
            content = _strip_json_fences(content)
        facts = json.loads(content)
        if isinstance(facts, list):
            return [str(item).strip() for item in facts if str(item).strip()]
    except Exception:
        return []
    return []


def _maybe_extract_and_store_memory(user_id: str, user_message: str, assistant_reply: str) -> None:
    facts = _extract_memory_facts(user_message, assistant_reply)
    if not facts:
        return
    for fact in facts:
        owner_type = _classify_owner_type(fact)
        tags = _infer_tags(fact)
        try:
            _ltm.add_memory(
                user_id=user_id,
                owner_type=owner_type,
                content=fact,
                tags=tags,
                importance=0.6,
                plasticity=0.3,
            )
        except Exception:
            continue


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or request.user_id
    persona = _preferences.get_persona(request.user_id)
    persona_settings = _persona_store.get_settings(request.user_id)
    all_traits = _persona_store.list_traits(request.user_id) if persona_settings else []
    active_traits = select_top_traits(all_traits)

    # Decay and prune LTM before retrieval
    _ltm.decay_importance(user_id=request.user_id, owner_type="user")
    _ltm.decay_importance(user_id=request.user_id, owner_type="assistant")
    _ltm.prune_caps(user_id=request.user_id)

    effect_name = classify_interaction_effect(request.message) if persona_settings else None
    mood_state = (
        _moods.apply_interaction_effect(request.user_id, effect_name, session_id=session_id)
        if effect_name
        else _moods.get_mood(request.user_id, session_id=session_id)
    ) if persona_settings else None

    memory_context = _gather_context(request.user_id)
    ltm_text, retrieved_memories = _retrieve_ltm_context(request.user_id, request.message)
    if ltm_text:
        memory_context = f"{memory_context}\n\nLong-term memory:\n{ltm_text}" if memory_context else f"Long-term memory:\n{ltm_text}"
    system_prompt = build_system_prompt(persona, _tools.list_tools(), memory_context)

    try:
        history = _sessions.get_history(session_id, max_age_minutes=20) if session_id else []
        messages = [{"role": "system", "content": system_prompt}, *history]
        step = _chat_once_with_history(messages, request.message)
    except OllamaError as exc:  # pragma: no cover - network/runtime guard
        raise HTTPException(status_code=502, detail=str(exc))

    response_payload = step["response"]
    llm_message = response_payload["message"].get("content", "").strip()
    messages = step["messages"]
    actions: List[Action] = []

    tool_call = _extract_structured_tool_call(response_payload)
    if not tool_call:
        tool_call = _parse_tool_call(llm_message)
    if tool_call:
        action = _execute_tool_call(tool_call, default_user_id=request.user_id)
        actions.append(action)
        assistant_tool_content = llm_message or json.dumps(
            {"tool": action.tool, "arguments": action.arguments}
        )
        messages.append({"role": "assistant", "content": assistant_tool_content})
        final_reply = _finalize_with_tool(messages, action)
        reply = final_reply
    else:
        reply = llm_message

    if active_traits and any(t.id for t in active_traits):
        _persona_store.record_trait_usage([t.id for t in active_traits if t.id is not None])

    if reply and persona_settings and mood_state:
        reply = _apply_personality_filter(request.message, reply, active_traits, mood_state)

    # Memory extraction: capture durable facts/preferences from the turn
    try:
        _maybe_extract_and_store_memory(request.user_id, request.message, reply)
    except Exception:
        pass

    # Merge redundant memories occasionally
    try:
        _ltm.merge_redundant(user_id=request.user_id, owner_type="user")
        _ltm.merge_redundant(user_id=request.user_id, owner_type="assistant")
    except Exception:
        pass

    if session_id:
        _sessions.append(session_id, request.user_id, "user", request.message)
        _sessions.append(session_id, request.user_id, "assistant", reply)
    return ChatResponse(reply=reply, actions=actions)


@app.get("/status", response_model=StatusResponse)
def status_endpoint() -> StatusResponse:
    llm_status = "ok"
    try:
        _ollama.generate("ping", options={"num_predict": 1})
    except Exception as exc:  # pragma: no cover - runtime guard
        llm_status = f"error: {exc}" if not isinstance(exc, OllamaError) else f"error: {exc}"

    memory_status = "ok"
    try:
        _preferences.get_all("healthcheck")
    except Exception as exc:  # pragma: no cover - runtime guard
        memory_status = f"error: {exc}"

    tools_status = "ok" if _tools.list_tools() else "empty"
    return StatusResponse(llm=llm_status, memory=memory_status, tools=tools_status)


__all__ = ["app"]
