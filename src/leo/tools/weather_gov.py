"""National Weather Service (weather.gov) tool adapter."""
from __future__ import annotations

from typing import Any, Dict

from .base import BaseTool, ToolResult


class WeatherGovForecastTool(BaseTool):
    """Fetch NWS forecast data for a latitude/longitude."""

    name = "weather.gov.forecast"
    description = "Get National Weather Service forecast for given coordinates (latitude and longitude)."
    input_schema = {
        "type": "object",
        "properties": {
            "latitude": {"type": "number", "description": "Decimal latitude (e.g., 47.6062)."},
            "longitude": {"type": "number", "description": "Decimal longitude (e.g., -122.3321)."},
            "hourly": {
                "type": "boolean",
                "description": "If true, include hourly forecast data when available.",
            },
            "hours": {
                "type": "integer",
                "minimum": 1,
                "maximum": 48,
                "description": "Limit of hourly periods to return (1-48).",
            },
        },
        "required": ["latitude", "longitude"],
    }

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=False,
            data=None,
            message="Weather tool is currently deprecated; no forecast was retrieved.",
        )


__all__ = ["WeatherGovForecastTool"]
