#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

import run_leadgen


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Self-contained LeadGen webhook runner.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Webhook bind host.")
    parser.add_argument("--port", type=int, default=8787, help="Webhook bind port.")
    parser.add_argument("--path", type=str, default="/webhook/lead-vetting-prod", help="Webhook path.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    # Force webhook mode and forward only webhook arguments.
    sys.argv = [
        sys.argv[0],
        "--mode",
        "webhook",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--path",
        args.path,
    ]
    return run_leadgen.main()


if __name__ == "__main__":
    sys.exit(main())
