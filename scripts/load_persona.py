"""Load persona traits into the SQLite preferences table."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Any

from leo.db import Database

DEFAULT_PERSONA_PATH = Path("data/persona.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="primary", help="User identifier to attach preferences to")
    parser.add_argument("--display-name", default="Primary User", help="Display name for the user entry")
    parser.add_argument(
        "--persona-path",
        default=DEFAULT_PERSONA_PATH,
        type=Path,
        help="Path to the persona JSON file",
    )
    return parser.parse_args()


def flatten_payload(prefix: str, value: Any, output: Dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            flatten_payload(next_prefix, child, output)
    elif isinstance(value, list):
        output[prefix] = json.dumps(value, separators=(",", ":"))
    elif isinstance(value, bool):
        output[prefix] = "true" if value else "false"
    else:
        output[prefix] = str(value)


def main() -> None:
    args = parse_args()
    persona_path: Path = args.persona_path
    if not persona_path.exists():
        raise SystemExit(f"Persona file not found: {persona_path}")

    payload = json.loads(persona_path.read_text())
    flattened: Dict[str, str] = {}
    for key, value in payload.items():
        flatten_payload(key, value, flattened)

    db = Database()
    db.initialize()

    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, display_name) VALUES (?, ?)",
            (args.user_id, args.display_name),
        )
        for key, value in flattened.items():
            conn.execute(
                """
                INSERT INTO preferences (user_id, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (args.user_id, key, value),
            )
        conn.commit()

    print(f"Loaded persona preferences for user '{args.user_id}' from {persona_path}")


if __name__ == "__main__":
    main()
