"""Simple CLI to talk to the LEO orchestrator."""
from __future__ import annotations

import argparse
import json

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000", help="Orchestrator base URL")
    parser.add_argument("--user-id", default="henry", help="User ID for chat requests")
    parser.add_argument("--session-id", default="cli", help="Session identifier to preserve history")
    parser.add_argument("--quiet", action="store_true", help="Only print assistant replies")
    return parser.parse_args()


def print_actions(actions: list[dict[str, object]]) -> None:
    if not actions:
        return
    print("-- Actions --")
    for action in actions:
        tool = action.get("tool")
        status = action.get("status")
        message = action.get("message")
        print(f"[{tool}] status={status} message={message}")
        if action.get("result"):
            pretty = json.dumps(action["result"], indent=2)
            print(pretty)


def main() -> None:
    args = parse_args()
    chat_endpoint = f"{args.base_url.rstrip('/')}/chat"
    print(f"Talking to {chat_endpoint} as user '{args.user_id}' session '{args.session_id}'")
    print("Type 'exit' or Ctrl+C to quit.\n")

    with httpx.Client(timeout=30.0) as client:
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

            payload = {
                "user_id": args.user_id,
                "session_id": args.session_id,
                "message": user_msg,
            }
            try:
                response = client.post(chat_endpoint, json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"Request failed: {exc}")
                continue

            body = response.json()
            if not args.quiet:
                print_actions(body.get("actions", []))
            print(f"leo > {body.get('reply', '').strip()}")


if __name__ == "__main__":
    main()
