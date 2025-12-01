"""Configuration helpers for LEO services."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OllamaConfig:
    """Settings for talking to the local Ollama server."""

    host: str = "http://localhost:11434"
    model: str = "gpt-oss:20b"
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "OllamaConfig":
        """Build config using environment variables with sane defaults."""

        return cls(
            host=os.getenv("OLLAMA_HOST", cls.host),
            model=os.getenv("MODEL_NAME", cls.model),
            timeout=float(os.getenv("OLLAMA_TIMEOUT", cls.timeout)),
        )


@dataclass(frozen=True)
class DatabaseConfig:
    """Settings for SQLite persistence."""

    path: str = str(Path("var") / "leo.db")

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(path=os.getenv("DB_PATH", cls.path))


@dataclass(frozen=True)
class HomeAssistantConfig:
    """Connection data for Home Assistant."""

    base_url: str = "http://localhost:8123"
    token: str | None = None

    @classmethod
    def from_env(cls) -> "HomeAssistantConfig":
        return cls(
            base_url=os.getenv("HA_BASE_URL", cls.base_url),
            token=os.getenv("HA_TOKEN", cls.token or ""),
        )

@dataclass(frozen=True)
class EmbeddingConfig:
    """Settings for embedding generation (via Ollama)."""

    host: str = "http://localhost:11434"
    model: str = "nomic-embed-text"
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        return cls(
            host=os.getenv("EMBED_HOST", cls.host),
            model=os.getenv("EMBED_MODEL", cls.model),
            timeout=float(os.getenv("EMBED_TIMEOUT", cls.timeout)),
        )


__all__ = ["OllamaConfig", "DatabaseConfig", "HomeAssistantConfig", "EmbeddingConfig"]
