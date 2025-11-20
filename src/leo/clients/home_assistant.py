"""Home Assistant HTTP client wrappers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import httpx

from leo.config import HomeAssistantConfig


class HomeAssistantError(RuntimeError):
    """Raised when a Home Assistant call fails."""


@dataclass
class HomeAssistantClient:
    config: HomeAssistantConfig
    _client: httpx.Client | None

    def __init__(self, config: HomeAssistantConfig | None = None) -> None:
        self.config = config or HomeAssistantConfig.from_env()
        headers = {}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        headers["Content-Type"] = "application/json"
        if self.config.token:
            self._client = httpx.Client(base_url=self.config.base_url, headers=headers, timeout=10.0)
        else:
            self._client = None

    def call_service(self, domain: str, service: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._client:
            return {
                "mode": "dry_run",
                "domain": domain,
                "service": service,
                "payload": payload,
            }

        endpoint = f"/api/services/{domain}/{service}"
        response = self._client.post(endpoint, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover
            raise HomeAssistantError(f"Failed HA call {domain}.{service}: {exc}") from exc
        return response.json()

    def close(self) -> None:
        if self._client:
            self._client.close()


__all__ = ["HomeAssistantClient", "HomeAssistantError"]
