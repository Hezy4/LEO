"""Playwright browser-use tool adapter."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

from .base import BaseTool, ToolResult

# Optional imports with fallbacks; any missing piece will be handled in run()
try:  # pragma: no cover - optional dependency
    from browser_use import Agent  # type: ignore
except Exception:  # pragma: no cover - library not installed or import error
    Agent = None  # type: ignore

try:  # pragma: no cover
    from browser_use.browser.browser import Browser, BrowserConfig  # type: ignore
except Exception:  # pragma: no cover
    Browser = None  # type: ignore
    BrowserConfig = None  # type: ignore

AssistantMemory = None
if Agent is not None:  # pragma: no cover - attempt multiple memory module paths
    try:
        from browser_use.memory.assistant import AssistantMemory  # type: ignore
    except Exception:
        try:
            from browser_use.memory.memory import AssistantMemory  # type: ignore
        except Exception:
            AssistantMemory = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from playwright.async_api import async_playwright  # type: ignore
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore


class BrowserUseTool(BaseTool):
    name = "web.browse"
    description = "Use Playwright browser-use to perform multi-step browsing and return visited content."
    input_schema = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What to accomplish on the web."},
            "start_url": {"type": "string", "description": "Optional starting URL."},
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 40, "default": 12},
            "timeout_seconds": {"type": "integer", "minimum": 10, "maximum": 180, "default": 60},
            "headless": {"type": "boolean", "default": True},
            "return_content": {"type": "boolean", "default": True},
            "provider": {"type": "string", "description": "LLM provider for browser-use (ollama|openai)."},
            "model": {"type": "string", "description": "Model name for the provider."},
            "temperature": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.2},
        },
        "required": ["goal"],
    }

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        if Agent is None or Browser is None or BrowserConfig is None or AssistantMemory is None:
            return ToolResult(
                success=False,
                message="browser-use is not installed. Install with `pip install browser-use playwright` "
                "and run `python -m playwright install chromium`.",
            )
        if async_playwright is None:
            return ToolResult(
                success=False,
                message="playwright is not available. Install with `pip install playwright` "
                "and run `python -m playwright install chromium`.",
            )

        goal = arguments["goal"]
        start_url = arguments.get("start_url")
        max_steps = int(arguments.get("max_steps", 12))
        max_steps = max(1, min(max_steps, 40))
        timeout_seconds = int(arguments.get("timeout_seconds", 60))
        timeout_seconds = max(10, min(timeout_seconds, 180))
        headless = bool(arguments.get("headless", True))
        return_content = bool(arguments.get("return_content", True))
        provider = arguments.get("provider") or os.getenv("BROWSER_USE_PROVIDER", "ollama")
        model = arguments.get("model") or os.getenv("BROWSER_USE_MODEL", "qwen3:4b")
        temperature = float(arguments.get("temperature", 0.2))

        try:
            result = self._run_async(
                goal=goal,
                start_url=start_url,
                max_steps=max_steps,
                timeout_seconds=timeout_seconds,
                headless=headless,
                return_content=return_content,
                provider=provider,
                model=model,
                temperature=temperature,
            )
        except Exception as exc:  # pragma: no cover - runtime safeguard
            return ToolResult(success=False, message=f"browser-use run failed: {exc}")

        payload = self._normalize_result(result, return_content=return_content)
        return ToolResult(success=True, data=payload, message=payload.get("summary"))

    def _run_async(
        self,
        *,
        goal: str,
        start_url: str | None,
        max_steps: int,
        timeout_seconds: int,
        headless: bool,
        return_content: bool,
        provider: str,
        model: str,
        temperature: float,
    ) -> Any:
        """Run the async browser-use flow, handling existing loops."""

        async def _runner() -> Any:
            llm = self._build_llm(provider=provider, model=model, temperature=temperature)
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=headless, args=["--disable-dev-shm-usage"])
                page = await browser.new_page()
                browser_wrapper = Browser(page, config=BrowserConfig(navigation_timeout=timeout_seconds * 1000))
                agent = Agent(
                    task=goal,
                    llm=llm,
                    browser=browser_wrapper,
                    memory=AssistantMemory(),
                )
                try:
                    result = await agent.run(max_steps=max_steps, start_url=start_url)
                finally:
                    await browser.close()
            return result

        try:
            return asyncio.run(_runner())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(_runner())
            finally:
                loop.close()
                asyncio.set_event_loop(None)

    def _build_llm(self, *, provider: str, model: str, temperature: float):
        """Build an LLM adapter for browser-use."""
        normalized = provider.lower()
        if normalized == "openai":
            try:
                from browser_use.llm.openai import OpenAIChat  # type: ignore

                return OpenAIChat(model=model, temperature=temperature)
            except Exception:
                try:
                    from browser_use.llm.openai import OpenAI  # type: ignore

                    return OpenAI(model=model, temperature=temperature)
                except Exception as exc:  # pragma: no cover - optional dependency
                    raise RuntimeError("OpenAI provider requested but browser-use OpenAI adapter is unavailable") from exc
        try:
            from browser_use.llm.ollama import Ollama  # type: ignore

            base_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            return Ollama(model=model, temperature=temperature, base_url=base_url)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("Failed to initialize Ollama adapter for browser-use") from exc

    def _normalize_result(self, result: Any, *, return_content: bool) -> Dict[str, Any]:
        """Coerce browser-use result into a compact dict."""
        if result is None:
            return {"summary": "No result returned"}

        data: Dict[str, Any]
        if isinstance(result, dict):
            data = result
        elif hasattr(result, "model_dump"):  # pydantic/dataclass
            data = result.model_dump()  # type: ignore
        elif hasattr(result, "__dict__"):
            data = {k: v for k, v in vars(result).items() if not k.startswith("_")}
        else:
            data = {"result": str(result)}

        actions = self._extract_actions(data)
        summary = data.get("summary") or data.get("final_result") or data.get("result")
        content = None
        if return_content:
            content = self._extract_content(data)

        payload = {"summary": summary or "Browser run completed", "actions": actions}
        if content:
            payload["content"] = content
        payload["raw"] = data
        return payload

    def _extract_actions(self, data: Dict[str, Any]) -> List[Dict[str, Any]] | None:
        actions = data.get("actions") or data.get("steps") or data.get("events")
        if not actions or not isinstance(actions, list):
            return None

        cleaned: List[Dict[str, Any]] = []
        for entry in actions:
            if isinstance(entry, dict):
                cleaned.append({k: entry[k] for k in ("url", "description", "action") if k in entry})
            else:
                cleaned.append({"action": str(entry)})
        return cleaned or None

    def _extract_content(self, data: Dict[str, Any]) -> str | None:
        candidates: List[str] = []
        for key in ("content", "text", "final_result", "result", "html"):
            value = data.get(key)
            if isinstance(value, str):
                candidates.append(value)
        if not candidates:
            return None
        joined = "\n\n".join(candidates)
        if len(joined) > 6000:
            return joined[:6000] + " ... [truncated]"
        return joined


__all__ = ["BrowserUseTool"]
