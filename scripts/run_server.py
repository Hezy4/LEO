"""Run the LEO FastAPI orchestrator."""
from __future__ import annotations

import argparse
import logging

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (DEBUG for server and LEO internals)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    log_level = "debug" if args.verbose else "info"
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    logging.getLogger("leo").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    uvicorn.run(
        "leo.orchestrator.service:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
