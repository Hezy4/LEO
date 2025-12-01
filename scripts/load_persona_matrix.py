"""Load persona matrix traits/settings into SQLite tables."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from leo.db import Database
from leo.memory.persona import PersonaStore

DEFAULT_MATRIX_PATH = Path("data/persona_matrix.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="primary", help="User identifier to attach persona to")
    parser.add_argument("--display-name", default="Primary User", help="Display name for the user entry")
    parser.add_argument(
        "--matrix-path",
        default=DEFAULT_MATRIX_PATH,
        type=Path,
        help="Path to the persona matrix JSON file",
    )
    parser.add_argument("--version", type=int, default=1, help="Version tag for the loaded matrix")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    matrix_path: Path = args.matrix_path
    if not matrix_path.exists():
        raise SystemExit(f"Persona matrix file not found: {matrix_path}")

    matrix = json.loads(matrix_path.read_text())
    db = Database()
    db.initialize()
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, display_name) VALUES (?, ?)",
            (args.user_id, args.display_name),
        )
        conn.commit()

    store = PersonaStore(db)
    store.load_matrix(args.user_id, matrix, version=args.version)
    print(f"Loaded persona matrix for user '{args.user_id}' from {matrix_path}")


if __name__ == "__main__":
    main()
