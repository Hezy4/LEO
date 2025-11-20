"""Home Assistant tool adapters."""
from __future__ import annotations

from typing import Any, Dict

from .base import BaseTool, ToolResult


class HomeAssistantSetLightsTool(BaseTool):
    name = "homeassistant.set_lights"
    description = "Adjust lights in a room or entity via Home Assistant."
    input_schema = {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Full HA entity ID"},
            "room": {"type": "string", "description": "Human-friendly room name"},
            "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
            "color_temp": {"type": "integer"},
        },
        "required": ["brightness"],
        "oneOf": [
            {"required": ["entity_id"]},
            {"required": ["room"]},
        ],
    }

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        client = self.context.home_assistant
        assert client is not None
        payload: Dict[str, Any] = {
            "brightness_pct": arguments.get("brightness"),
        }
        if arguments.get("entity_id"):
            payload["entity_id"] = arguments["entity_id"]
        if arguments.get("color_temp"):
            payload["color_temp"] = arguments["color_temp"]
        if arguments.get("room"):
            payload["area_id"] = arguments["room"].lower().replace(" ", "_")
        result = client.call_service("light", "turn_on", payload)
        return ToolResult(success=True, data=result, message="Lights updated")


class HomeAssistantRunSceneTool(BaseTool):
    name = "homeassistant.run_scene"
    description = "Activate a Home Assistant scene."
    input_schema = {
        "type": "object",
        "properties": {
            "scene_id": {"type": "string", "description": "Scene entity ID"},
        },
        "required": ["scene_id"],
    }

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        client = self.context.home_assistant
        assert client is not None
        payload = {"entity_id": arguments["scene_id"]}
        result = client.call_service("scene", "turn_on", payload)
        return ToolResult(success=True, data=result, message="Scene executed")


__all__ = ["HomeAssistantSetLightsTool", "HomeAssistantRunSceneTool"]
