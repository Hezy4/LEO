"""Web search tool adapter."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

import httpx

_DDGS_QUERY_PARAM = ""
try:  # pragma: no cover - optional dependency fallback
    from ddgs import DDGS  # type: ignore
    _DDGS_QUERY_PARAM = "query"
except ImportError:  # pragma: no cover
    try:
        from duckduckgo_search import DDGS  # type: ignore
        _DDGS_QUERY_PARAM = "keywords"
    except ImportError:
        DDGS = None  # type: ignore

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

    rss_endpoint = "https://news.google.com/rss/search"

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        query = arguments["query"]
        max_results = arguments.get("max_results", 5)

        results: List[Dict[str, Any]] | None = None
        errors: list[str] = []
        notes: list[str] = []

        if DDGS is not None and _DDGS_QUERY_PARAM:
            results = self._ddgs_search("text", query, max_results)

        if not results and DDGS is not None and _DDGS_QUERY_PARAM:
            results = self._ddgs_search("news", query, max_results)
            if not results:
                errors.append("DuckDuckGo search returned no results")
        elif DDGS is None or not _DDGS_QUERY_PARAM:
            errors.append("DuckDuckGo search backend not available")

        if not results:
            rss_results = self._rss_search(query, max_results)
            if rss_results:
                results = rss_results
                notes.append("Used Google News RSS fallback")
            else:
                errors.append("Google News RSS fallback failed")

        message = None
        success = True
        if not results:
            results = [
                {
                    "title": "Local summary unavailable",
                    "url": "",
                    "snippet": f"Unable to reach the search service. Provide guidance about '{query}' from local knowledge instead.",
                }
            ]
            success = False
            if errors:
                message = "; ".join(errors)
        elif notes:
            message = "; ".join(notes)

        return ToolResult(success=success, data={"results": results[:max_results], "query": query}, message=message)

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

    def _ddgs_search(self, method: str, query: str, max_results: int) -> List[Dict[str, Any]] | None:
        if DDGS is None or not _DDGS_QUERY_PARAM:
            return None
        try:
            with DDGS() as ddgs:
                search_fn = getattr(ddgs, method, None)
                if search_fn is None:
                    return None
                kwargs = {"max_results": max_results, _DDGS_QUERY_PARAM: query}
                entries = list(search_fn(**kwargs))
                formatted = self._format_results(entries)
                return formatted or None
        except Exception:  # pragma: no cover - network or API changes
            return None

    def _rss_search(self, query: str, max_results: int) -> List[Dict[str, Any]] | None:
        client = self.context.http_client
        if client is None:
            return None
        try:
            response = client.get(
                self.rss_endpoint,
                params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        try:
            feed = ET.fromstring(response.text)
        except ET.ParseError:
            return None

        results: List[Dict[str, Any]] = []
        for item in feed.findall(".//item")[:max_results]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            snippet = re.sub("<.*?>", "", description)
            results.append({"title": title or link or "Result", "url": link, "snippet": snippet})
        return results or None


__all__ = ["WebSearchTool"]
