"""Email sending tool (local outbox stub)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .base import BaseTool, ToolResult
from .context import ToolContext


class EmailSendTool(BaseTool):
    name = "email.send"
    description = "Compose an email and deposit it into a local outbox."
    input_schema = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["user_id", "to", "subject", "body"],
    }

    def __init__(self, context: ToolContext | None = None, outbox_dir: Path | None = None) -> None:
        super().__init__(context)
        self.outbox_dir = Path(outbox_dir or Path("var") / "outbox")
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        payload = {
            "user_id": arguments["user_id"],
            "to": arguments["to"],
            "subject": arguments["subject"],
            "body": arguments["body"],
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        filename = self._write_outbox(payload)
        return ToolResult(success=True, data={"outbox_file": str(filename)}, message="Email staged")

    def _write_outbox(self, payload: Dict[str, Any]) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        filename = self.outbox_dir / f"email_{timestamp}.json"
        filename.write_text(json.dumps(payload, indent=2))
        return filename


__all__ = ["EmailSendTool"]
