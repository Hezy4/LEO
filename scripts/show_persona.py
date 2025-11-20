"""Print persona preferences for a user."""
from __future__ import annotations

import argparse
import pprint

from leo.memory import PreferenceStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="henry")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = PreferenceStore()
    persona = store.get_persona(args.user_id)
    pprint.pprint(persona)


if __name__ == "__main__":
    main()
