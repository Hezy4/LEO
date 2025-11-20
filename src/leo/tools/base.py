"""Tool interface definitions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

from .context import ToolContext


@dataclass(slots=True)
class ToolResult:
    success: bool
    data: Any | None = None
    message: str | None = None


class ToolExecutionError(RuntimeError):
    """Raised when a tool fails to execute."""


class BaseTool(ABC):
    """Base class for all tool adapters."""

    name: str
    description: str
    input_schema: Dict[str, Any] = {}

    def __init__(self, context: ToolContext | None = None) -> None:
        self.context = context or ToolContext()

    @abstractmethod
    def run(self, arguments: Dict[str, Any]) -> ToolResult:  # pragma: no cover - abstract
        raise NotImplementedError


__all__ = ["BaseTool", "ToolResult", "ToolExecutionError"]
