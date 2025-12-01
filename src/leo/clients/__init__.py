"""Client implementations for third-party services."""

from .ollama_client import OllamaClient, OllamaError
from .home_assistant import HomeAssistantClient, HomeAssistantError
from .embedding_client import EmbeddingClient, EmbeddingError

__all__ = [
    "OllamaClient",
    "OllamaError",
    "HomeAssistantClient",
    "HomeAssistantError",
    "EmbeddingClient",
    "EmbeddingError",
]
