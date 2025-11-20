"""Web search tool adapter."""
from __future__ import annotations

from typing import Any, Dict, List

import httpx

try:  # pragma: no cover - optional dependency fallback
    from duckduckgo_search import DDGS
except ImportError:  # pragma: no cover
    DDGS = None

from .base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    name = "web.search"
    description = "Perform a lightweight web search and return top snippets."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    }

    endpoint = "https://ddg-api.nolanlawson.com/v1/search"

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        query = arguments["query"]
        max_results = arguments.get("max_results", 5)

        results: List[Dict[str, Any]] | None = None

        if DDGS is not None:
            try:
                with DDGS() as ddgs:
                    entries = list(ddgs.text(query, max_results=max_results))
                    formatted = self._format_results(entries)
                    results = formatted or None
            except Exception:  # pragma: no cover - network/HTML changes
                results = None

        if not results and DDGS is not None:
            if DDGS is not None:
                try:
                    with DDGS() as ddgs:
                        entries = list(ddgs.news(query, max_results=max_results))
                        formatted = self._format_results(entries)
                        results = formatted or None
                except Exception:
                    results = None

        if not results:
            client = self.context.http_client
            assert client is not None
            params = {"q": query, "type": "text"}
            try:
                response = client.get(self.endpoint, params=params)
                response.raise_for_status()
                body = response.json()
                results = self._format_results(body.get("data", [])[:max_results])
            except (httpx.HTTPError, ValueError, KeyError):
                results = None

        if not results:
            results = [
                {
                    "title": "Local summary unavailable",
                    "url": "",
                    "snippet": f"Unable to reach the search service. Provide guidance about '{query}' from local knowledge instead.",
                }
            ]

        return ToolResult(success=True, data={"results": results[:max_results], "query": query})

    def _format_results(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted: List[Dict[str, Any]] = []
        for entry in entries:
            formatted.append(
                {
                    "title": entry.get("title") or entry.get("url", "Result"),
                    "url": entry.get("href") or entry.get("url", ""),
                    "snippet": entry.get("body") or entry.get("snippet") or entry.get("excerpt", ""),
                }
            )
        return formatted


__all__ = ["WebSearchTool"]
