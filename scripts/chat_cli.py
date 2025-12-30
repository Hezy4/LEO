"""Text-first agent that mirrors the voice agent flow without audio I/O."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_CANDIDATES = [Path(".env"), PROJECT_ROOT / ".env"]


def load_env_file() -> None:
    loaded: set[Path] = set()
    for raw_path in ENV_CANDIDATES:
        candidate = raw_path.expanduser()
        if not candidate.exists():
            continue
        resolved = candidate.resolve()
        if resolved in loaded:
            continue
        loaded.add(resolved)
        for line in resolved.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000", help="Orchestrator base URL")
    parser.add_argument("--user-id", default="henry", help="User ID for chat requests")
    parser.add_argument("--session-id", default="voice", help="Session identifier to preserve history")
    parser.add_argument("--quiet", action="store_true", help="Suppress tool/action logs")
    return parser.parse_args()


def send_chat(client: httpx.Client, base_url: str, user_id: str, session_id: str, message: str, quiet: bool) -> str:
    payload = {"user_id": user_id, "session_id": session_id, "message": message}
    response = client.post(f"{base_url.rstrip('/')}/chat", json=payload, timeout=120)
    response.raise_for_status()
    body = response.json()
    if not quiet:
        for action in body.get("actions", []):
            print(f"[tool] {action.get('tool')} -> {action.get('status')}: {action.get('message')}")
            if action.get("result"):
                print(json.dumps(action["result"], indent=2))
    return body.get("reply", "")


def main() -> None:
    load_env_file()
    args = parse_args()
    chat_endpoint = f"{args.base_url.rstrip('/')}/chat"
    print(f"Talking to {chat_endpoint} as user '{args.user_id}' session '{args.session_id}'")
    print("Type 'exit' or Ctrl+C to quit.\n")

    with httpx.Client(timeout=60.0) as client:
        while True:
            try:
                user_msg = input("you > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting chat CLI.")
                break

            if not user_msg:
                continue
            if user_msg.lower() in {"exit", "quit"}:
                print("Goodbye!")
                break

            try:
                reply = send_chat(client, args.base_url, args.user_id, args.session_id, user_msg, args.quiet)
            except httpx.HTTPError as exc:
                print(f"Request failed: {exc}")
                continue

            print(f"leo > {reply.strip()}")


if __name__ == "__main__":
    main()
