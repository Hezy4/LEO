"""FastAPI app exposing the LEO orchestrator."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from leo.clients import OllamaClient, OllamaError
from leo.memory import PreferenceStore, TaskStore, ReminderStore, EpisodicMemoryStore, SessionStore
from leo.tools import ToolRegistry

from .prompts import build_system_prompt, build_memory_context

SPEECH_FRIENDLY_REMINDER = (
    "Provide the final response in plain conversational sentences suitable for text-to-speech. "
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
_preferences = PreferenceStore()
_tools = ToolRegistry.default()
_tasks = TaskStore()
_reminders = ReminderStore()
_episodes = EpisodicMemoryStore()
_sessions = SessionStore()


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


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest) -> ChatResponse:
    persona = _preferences.get_persona(request.user_id)
    memory_context = _gather_context(request.user_id)
    system_prompt = build_system_prompt(persona, _tools.list_tools(), memory_context)

    try:
        session_id = request.session_id or request.user_id
        history = _sessions.get_history(session_id) if session_id else []
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

    session_id = request.session_id or request.user_id
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
