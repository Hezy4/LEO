"""Tool registry for orchestrator use."""
from __future__ import annotations

from typing import Dict, Iterable, List

from .base import BaseTool, ToolResult
from .context import ToolContext
from .reminders import RemindersCreateTool
from .tasks import TasksCreateTool, TasksListTool, TasksUpdateStatusTool
from .web import WebSearchTool
from .homeassistant import HomeAssistantRunSceneTool, HomeAssistantSetLightsTool
from .gmail import GmailGetMessageTool, GmailListMessagesTool
from .weather_gov import WeatherGovForecastTool


class ToolRegistry:
    def __init__(self, context: ToolContext | None = None) -> None:
        self.context = context or ToolContext()
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered")
        return self._tools[name]

    def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self.get(name)
        return tool.run(arguments)

    def list_tools(self) -> List[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    @classmethod
    def default(cls) -> "ToolRegistry":
        context = ToolContext()
        registry = cls(context=context)
        for tool in (
            TasksCreateTool(context),
            TasksListTool(context),
            TasksUpdateStatusTool(context),
            RemindersCreateTool(context),
            WebSearchTool(context),
            GmailListMessagesTool(context),
            GmailGetMessageTool(context),
            HomeAssistantSetLightsTool(context),
            HomeAssistantRunSceneTool(context),
            WeatherGovForecastTool(context),
        ):
            registry.register(tool)
        return registry


__all__ = ["ToolRegistry"]
