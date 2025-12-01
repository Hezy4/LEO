"""National Weather Service (weather.gov) tool adapter."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseTool, ToolResult
from .context import ToolContext


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

    def __init__(
        self,
        context: ToolContext | None = None,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(context)
        self.user_agent = user_agent or os.getenv(
            "WEATHER_GOV_USER_AGENT",
            "LEO/0.1.0 (contact: change-me@example.com)",
        )
        self.timeout = float(timeout or os.getenv("WEATHER_GOV_TIMEOUT", "15.0"))

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        lat = arguments["latitude"]
        lon = arguments["longitude"]
        hourly = bool(arguments.get("hourly"))
        hours = self._coerce_hours(arguments.get("hours"))

        headers = {"Accept": "application/geo+json"}
        if self.user_agent:
            headers["User-Agent"] = self.user_agent

        client = self.context.http_client
        assert client is not None

        point_url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
        point_result = self._fetch_json(client, point_url, headers)
        if not point_result["success"]:
            return ToolResult(success=False, message=point_result["error"])

        point_props = point_result["data"].get("properties") or {}
        grid_id = point_props.get("gridId")
        grid_x = point_props.get("gridX")
        grid_y = point_props.get("gridY")
        if not (grid_id and grid_x is not None and grid_y is not None):
            return ToolResult(success=False, message="weather.gov lookup did not return grid data")

        location_props = (point_props.get("relativeLocation") or {}).get("properties") or {}
        location = {
            "city": location_props.get("city"),
            "state": location_props.get("state"),
            "timezone": point_props.get("timeZone"),
        }

        forecast_url = point_props.get("forecast") or f"https://api.weather.gov/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast"
        forecast_result = self._fetch_json(client, forecast_url, headers)
        if not forecast_result["success"]:
            return ToolResult(success=False, message=forecast_result["error"])

        forecast_periods = self._normalize_periods(
            (forecast_result["data"].get("properties") or {}).get("periods") or []
        )

        hourly_payload: Dict[str, Any] | None = None
        if hourly:
            hourly_url = point_props.get("forecastHourly") or f"https://api.weather.gov/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast/hourly"
            hourly_result = self._fetch_json(client, hourly_url, headers)
            if hourly_result["success"]:
                periods = (hourly_result["data"].get("properties") or {}).get("periods") or []
                hourly_payload = self._normalize_periods(periods, limit=hours)
            else:
                hourly_payload = {"error": hourly_result["error"]}

        payload = {
            "coordinates": {"latitude": lat, "longitude": lon},
            "location": location,
            "forecast": forecast_periods,
            "hourly": hourly_payload,
            "source": "api.weather.gov",
        }
        return ToolResult(success=True, data=payload, message="Forecast retrieved")

    def _fetch_json(
        self, client: httpx.Client, url: str, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        try:
            resp = client.get(url, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
        except (httpx.HTTPError, ValueError) as exc:
            return {"success": False, "error": f"weather.gov request failed: {exc}"}

    def _normalize_periods(self, periods: List[Dict[str, Any]], limit: Optional[int] = None) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for entry in periods:
            normalized.append(
                {
                    "name": entry.get("name"),
                    "startTime": entry.get("startTime"),
                    "endTime": entry.get("endTime"),
                    "isDaytime": entry.get("isDaytime"),
                    "temperature": entry.get("temperature"),
                    "temperatureUnit": entry.get("temperatureUnit"),
                    "windSpeed": entry.get("windSpeed"),
                    "windDirection": entry.get("windDirection"),
                    "shortForecast": entry.get("shortForecast"),
                    "detailedForecast": entry.get("detailedForecast"),
                    "probabilityOfPrecipitation": (entry.get("probabilityOfPrecipitation") or {}).get("value"),
                }
            )
        if limit is not None:
            return normalized[:limit]
        return normalized

    def _coerce_hours(self, raw: Any) -> int | None:
        if raw is None:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return max(1, min(value, 48))


__all__ = ["WeatherGovForecastTool"]
