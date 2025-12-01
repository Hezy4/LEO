"""Embedding client using a local Ollama model (nomic-embed-text by default)."""
from __future__ import annotations

import httpx
import json
import subprocess
import shlex

from leo.config import EmbeddingConfig


class EmbeddingError(RuntimeError):
    """Raised when embedding generation fails."""


class EmbeddingClient:
    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or EmbeddingConfig.from_env()
        self._client = httpx.Client(timeout=self.config.timeout)

    def embed(self, text: str) -> list[float]:
        payload = {
            "model": self.config.model,
            "input": text,
        }
        endpoints = ["/api/embeddings", "/api/embed"]
        errors: list[str] = []
        for path in endpoints:
            try:
                resp = self._client.post(f"{self.config.host}{path}", json=payload)
                resp.raise_for_status()
                data = resp.json()
                embedding = data.get("embedding") or data.get("embeddings")
                # Ollama returns {"embedding": [...]} or {"embeddings": [[...]]}
                if isinstance(embedding, list):
                    if embedding and isinstance(embedding[0], list):
                        return embedding[0]
                    return embedding
                raise EmbeddingError("Unexpected embedding payload")
            except Exception as exc:  # pragma: no cover - runtime guard
                errors.append(f"{path}: {exc}")
                continue
        # Fallback to CLI if HTTP endpoints are unavailable (older Ollama versions)
        try:
            return self._embed_via_cli(text)
        except Exception as exc:  # pragma: no cover - runtime guard
            errors.append(f"cli: {exc}")
        raise EmbeddingError("; ".join(errors))

    def _embed_via_cli(self, text: str) -> list[float]:
        cmd = ["ollama", "embed", "-m", self.config.model, text]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        # Output may be JSON or plain; try JSON first
        try:
            data = json.loads(output)
            embedding = data.get("embedding") or data.get("embeddings")
            if isinstance(embedding, list):
                if embedding and isinstance(embedding[0], list):
                    return embedding[0]
                return embedding
        except json.JSONDecodeError:
            pass
        # If not JSON, attempt to parse whitespace-separated floats
        try:
            return [float(x) for x in output.split()]
        except Exception as exc:
            raise EmbeddingError(f"Failed to parse CLI embedding output: {exc}") from exc

    def close(self) -> None:
        self._client.close()


__all__ = ["EmbeddingClient", "EmbeddingError"]
