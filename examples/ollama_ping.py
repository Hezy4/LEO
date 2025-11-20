"""Simple script to verify the Ollama client works."""
from __future__ import annotations

from leo.clients import OllamaClient


def main() -> None:
    client = OllamaClient()
    response = client.generate("Say hello from LEO in one sentence.")
    print(response)


if __name__ == "__main__":
    main()
