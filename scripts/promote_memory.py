"""Trigger manual promotion from short-term session history into long-term memory."""
from __future__ import annotations

import argparse
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000", help="LEO orchestrator base URL")
    parser.add_argument("--user-id", default="henry", help="User ID whose memories should be promoted")
    parser.add_argument("--session-id", help="Session ID to pull short-term history from (defaults to user ID)")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=6,
        help="Number of most recent user/assistant exchanges to promote (0 to skip limit)",
    )
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=None,
        help="Ignore history older than this many minutes (0 to disable time filtering)",
    )
    parser.add_argument(
        "--run-maintenance",
        action="store_true",
        help="Also run decay/pruning/merge maintenance after promotion completes.",
    )
    return parser.parse_args()


def promote(payload: dict[str, Any], endpoint: str) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(endpoint, json=payload)
        response.raise_for_status()
        return response.json()


def main() -> None:
    args = parse_args()
    endpoint = f"{args.base_url.rstrip('/')}/memory/promote"
    payload: dict[str, Any] = {
        "user_id": args.user_id,
        "session_id": args.session_id,
        "max_turns": args.max_turns,
        "run_maintenance": args.run_maintenance,
    }
    if args.max_age_minutes is not None:
        payload["max_age_minutes"] = args.max_age_minutes

    try:
        result = promote(payload, endpoint)
    except httpx.HTTPError as exc:
        raise SystemExit(f"Promotion request failed: {exc}") from exc

    added = result.get("added", 0)
    maintenance = result.get("maintenance_run", False)
    stored = result.get("stored") or []

    print(f"Promotion completed: added {added} memories (maintenance_run={maintenance}).")
    if stored:
        print("-- Stored entries --")
        for item in stored:
            owner = item.get("owner_type", "user")
            content = item.get("content") or item.get("summary") or ""
            tags = item.get("tags") or []
            print(f"[{owner}] {content} (tags: {', '.join(tags) if tags else 'none'})")


if __name__ == "__main__":
    main()
