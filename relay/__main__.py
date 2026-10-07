"""Command-line entry point for the experimental Picochess relay."""

from __future__ import annotations

import argparse
import asyncio
import logging

from .relay import PicoEndpoint, Relay, RelayError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Relay engine moves between two NOEBOARD Picochess instances."
    )
    parser.add_argument("first_url", help="base URL of Picochess instance A")
    parser.add_argument("second_url", help="base URL of Picochess instance B")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="connection, initial-state, HTTP, and move-ack timeout in seconds (default: 10)",
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.timeout <= 0:
            raise RelayError("timeout must be greater than zero")
        first = PicoEndpoint("A", args.first_url, args.timeout)
        second = PicoEndpoint("B", args.second_url, args.timeout)
        if first.channel_url == second.channel_url:
            raise RelayError("the two Picochess URLs resolve to the same endpoint")
        relay = Relay(first, second, args.timeout)
        await relay.run()
    except RelayError as exc:
        logging.getLogger(__name__).error("STOPPED: %s", exc)
        return 1
    return 0


def main() -> int:
    args = _parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("STOPPED by operator")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
