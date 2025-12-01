"""Gmail read-only tool adapters."""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError as exc:  # pragma: no cover - import guard
    Credentials = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    build = None  # type: ignore[assignment]
    HttpError = Exception
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from .base import BaseTool, ToolResult, ToolExecutionError
from .context import ToolContext

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_TOKEN_PATH = Path(os.getenv("LEO_GMAIL_TOKEN", "~/.config/leo/google_token.json")).expanduser()
MAX_BODY_CHARS = 8000


def _ensure_dependencies() -> None:
    if _IMPORT_ERROR is not None:
        raise ToolExecutionError(
            "Gmail tools require google-api-python-client, google-auth, "
            "google-auth-oauthlib, and google-auth-httplib2 to be installed."
        ) from _IMPORT_ERROR


def _load_credentials(token_path: Path) -> Credentials:
    _ensure_dependencies()
    if not token_path.exists():
        raise ToolExecutionError(
            f"Gmail token not found at {token_path}. Authenticate once with the "
            "https://www.googleapis.com/auth/gmail.readonly scope and retry."
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)  # type: ignore[arg-type]
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())  # type: ignore[call-arg]
        token_path.write_text(creds.to_json())
    if not creds or not creds.valid:
        raise ToolExecutionError(
            "Gmail credentials are invalid or expired. Re-authenticate with the read-only scope."
        )
    return creds


def _build_service(token_path: Path):
    creds = _load_credentials(token_path)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)  # type: ignore[call-arg]


def _extract_headers(raw_headers: List[Dict[str, Any]]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for header in raw_headers or []:
        name = header.get("name")
        value = header.get("value")
        if name and value:
            headers[name.lower()] = value
    return headers


def _decode_body(data: str | bytes | None) -> str:
    if not data:
        return ""
    raw_bytes = data if isinstance(data, (bytes, bytearray)) else data.encode()
    try:
        decoded = base64.urlsafe_b64decode(raw_bytes)
        return decoded.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _strip_html(text: str) -> str:
    # Basic HTML to text fallback to avoid pulling in heavy dependencies
    cleaned = re.sub(r"(?s)<style.*?>.*?</style>", "", text)
    cleaned = re.sub(r"(?s)<script.*?>.*?</script>", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_body(payload: Dict[str, Any]) -> str:
    body_data = payload.get("body", {}).get("data")
    if body_data:
        return _decode_body(body_data)

    for part in payload.get("parts", []) or []:
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain":
            text = _decode_body(part.get("body", {}).get("data"))
            if text:
                return text
        if mime_type.startswith("multipart/"):
            nested = _extract_body(part)
            if nested:
                return nested

    for part in payload.get("parts", []) or []:
        mime_type = part.get("mimeType", "")
        if mime_type == "text/html":
            html = _decode_body(part.get("body", {}).get("data"))
            if html:
                return _strip_html(html)
    return ""


def _sanitize_body(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: List[str] = []
    for line in lines:
        if line.strip() == "--":
            break
        lowered = line.strip().lower()
        if lowered.startswith("unsubscribe") or lowered.startswith("confidentiality notice"):
            break
        cleaned.append(line)
    condensed = "\n".join(cleaned).strip()
    if len(condensed) > MAX_BODY_CHARS:
        return condensed[:MAX_BODY_CHARS].rstrip() + " ..."
    return condensed


def _extract_parts(payload: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
    headers = _extract_headers(payload.get("headers", []))
    body = _sanitize_body(_extract_body(payload))
    return body, headers


class GmailListMessagesTool(BaseTool):
    name = "gmail.list_messages"
    description = "List recent Gmail messages (read-only) with light metadata and snippets."
    input_schema = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
            "query": {
                "type": "string",
                "description": "Optional Gmail search query, e.g., 'is:unread newer_than:7d'.",
            },
            "label_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional label IDs to filter (e.g., INBOX).",
            },
            "token_path": {
                "type": "string",
                "description": "Path to the authorized_user token JSON (default ~/.config/leo/google_token.json).",
            },
        },
        "required": ["user_id"],
    }

    def __init__(self, context: ToolContext | None = None, token_path: Path | None = None) -> None:
        super().__init__(context)
        self.token_path = Path(token_path or DEFAULT_TOKEN_PATH).expanduser()

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        token_path = Path(arguments.get("token_path") or self.token_path).expanduser()
        max_results = arguments.get("max_results", 10)
        try:
            limit = int(max_results)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 50))
        query = arguments.get("query") or None
        label_ids_arg = arguments.get("label_ids") or None
        label_ids = label_ids_arg
        if isinstance(label_ids_arg, str):
            label_ids = [label_ids_arg]

        try:
            service = _build_service(token_path)
            result = (
                service.users()
                .messages()
                .list(userId="me", maxResults=limit, q=query, labelIds=label_ids)
                .execute()
            )
            messages = result.get("messages", [])
            details: List[Dict[str, Any]] = []
            for entry in messages:
                message_id = entry.get("id")
                if not message_id:
                    continue
                meta = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=message_id,
                        format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    )
                    .execute()
                )
                headers = _extract_headers(meta.get("payload", {}).get("headers", []))
                details.append(
                    {
                        "id": meta.get("id"),
                        "thread_id": meta.get("threadId"),
                        "snippet": meta.get("snippet"),
                        "subject": headers.get("subject"),
                        "from": headers.get("from"),
                        "date": headers.get("date"),
                        "label_ids": meta.get("labelIds", []),
                    }
                )
            return ToolResult(
                success=True,
                data={"messages": details, "count": len(details)},
                message="Fetched Gmail messages (read-only).",
            )
        except HttpError as exc:
            raise ToolExecutionError(f"Gmail API error: {exc}") from exc


class GmailGetMessageTool(BaseTool):
    name = "gmail.get_message"
    description = "Fetch a single Gmail message (read-only) and return sanitized plain text for summarization."
    input_schema = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "message_id": {"type": "string"},
            "token_path": {
                "type": "string",
                "description": "Path to the authorized_user token JSON (default ~/.config/leo/google_token.json).",
            },
        },
        "required": ["user_id", "message_id"],
    }

    def __init__(self, context: ToolContext | None = None, token_path: Path | None = None) -> None:
        super().__init__(context)
        self.token_path = Path(token_path or DEFAULT_TOKEN_PATH).expanduser()

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        token_path = Path(arguments.get("token_path") or self.token_path).expanduser()
        message_id = arguments["message_id"]

        try:
            service = _build_service(token_path)
            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            payload = message.get("payload", {}) or {}
            body, headers = _extract_parts(payload)
            data = {
                "id": message.get("id"),
                "thread_id": message.get("threadId"),
                "subject": headers.get("subject"),
                "from": headers.get("from"),
                "to": headers.get("to"),
                "date": headers.get("date"),
                "snippet": message.get("snippet"),
                "body": body,
                "label_ids": message.get("labelIds", []),
                "notice": (
                    "Read-only fetch. Do not store raw email content; summarize only if needed."
                ),
            }
            return ToolResult(success=True, data=data, message="Fetched Gmail message (read-only).")
        except HttpError as exc:
            raise ToolExecutionError(f"Gmail API error: {exc}") from exc


__all__ = ["GmailListMessagesTool", "GmailGetMessageTool"]
