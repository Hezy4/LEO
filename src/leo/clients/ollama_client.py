"""Ollama client helpers."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional

import httpx

from leo.config import OllamaConfig


class OllamaError(RuntimeError):
    """Raised when the Ollama backend returns an error."""


class OllamaClient:
    """Thin wrapper over the local Ollama HTTP API."""

    def __init__(self, config: Optional[OllamaConfig] = None) -> None:
        self.config = config or OllamaConfig.from_env()
        self._client = httpx.Client(base_url=self.config.host, timeout=self.config.timeout)

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        options: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> str | Iterator[str]:
        """Call the `/api/generate` endpoint.

        Args:
            prompt: User prompt.
            system_prompt: Optional system message injected before the prompt.
            options: Extra ollama-specific generation options.
            stream: When True yields tokens incrementally.
        """

        payload: Dict[str, Any] = {"model": self.config.model, "prompt": prompt}
        if system_prompt:
            payload["system"] = system_prompt
        if options:
            payload["options"] = options

        if stream:
            return self._stream_generate(payload)

        response = self._client.post("/api/generate", json=payload)
        self._raise_for_error(response)
        body = self._decode_json_body(response)
        return body.get("response", "")

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        options: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Dict[str, Any] | Iterator[Dict[str, Any]]:
        """Call the `/api/chat` endpoint with a message list."""

        payload: Dict[str, Any] = {"model": self.config.model, "messages": messages}
        if options:
            payload["options"] = options

        if stream:
            return self._stream_chat(payload)

        response = self._client.post("/api/chat", json=payload)
        self._raise_for_error(response)
        return self._decode_json_body(response)

    def _stream_generate(self, payload: Dict[str, Any]) -> Iterator[str]:
        with self._client.stream("POST", "/api/generate", json=payload) as response:
            self._raise_for_error(response)
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                yield chunk.get("response", "")

    def _stream_chat(self, payload: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        with self._client.stream("POST", "/api/chat", json=payload) as response:
            self._raise_for_error(response)
            for line in response.iter_lines():
                if not line:
                    continue
                yield json.loads(line)

    def _raise_for_error(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - thin wrapper
            detail = exc.response.text
            raise OllamaError(f"Ollama request failed: {detail}") from exc

    def _decode_json_body(self, response: httpx.Response) -> Dict[str, Any]:
        """Decode standard or newline-delimited JSON bodies from Ollama."""

        text = response.text.strip()
        if not text:
            raise OllamaError("Received empty response body from Ollama")

        # Ollama returns newline-delimited JSON even when streaming is disabled.
        chunks: List[Dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))

        if not chunks:
            raise OllamaError("Received invalid response body from Ollama")

        if len(chunks) == 1:
            return chunks[0]

        final_payload = chunks[-1].copy()

        if any("response" in chunk for chunk in chunks):
            final_payload["response"] = "".join(chunk.get("response", "") for chunk in chunks)

        if any("message" in chunk for chunk in chunks):
            message: Dict[str, Any] = final_payload.get("message", {}).copy()
            message["content"] = "".join(
                chunk.get("message", {}).get("content", "") for chunk in chunks
            )
            final_payload["message"] = message

        return final_payload


__all__ = ["OllamaClient", "OllamaError"]
