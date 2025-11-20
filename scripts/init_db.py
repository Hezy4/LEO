"""Initialize the local LEO SQLite database."""
from __future__ import annotations

from leo.db.database import Database


def main() -> None:
    db = Database()
    db.initialize()
    print(f"Initialized database at {db.path}")


if __name__ == "__main__":
    main()
