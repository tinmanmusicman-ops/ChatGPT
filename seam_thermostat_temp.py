#!/usr/bin/env python3
"""Connect to the Seam sandbox and report the current thermostat temperature."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print the current thermostat temperature from Seam sandbox."
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("seam_config.json"),
        help="Path to the Seam config file (default: seam_config.json).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Emit debug details about API calls.",
    )
    return parser.parse_args()


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    required = ["client_id", "client_secret", "thermostat_id", "base_url"]
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        raise KeyError(f"Missing required config keys: {missing}")
    cfg.setdefault("token_url", f"{cfg['base_url'].rstrip('/')}/oauth/token")
    cfg.setdefault(
        "thermostat_endpoint",
        f"{cfg['base_url'].rstrip('/')}/v1/thermostats/{cfg['thermostat_id']}",
    )
    cfg.setdefault("timeout_seconds", 20)
    return cfg


def request_token(cfg: Dict[str, Any], verbose: bool = False) -> str:
    data = {"grant_type": "client_credentials"}
    token_url = cfg["token_url"]
    if verbose:
        print(f"Requesting OAuth token from {token_url}")
    resp = requests.post(
        token_url,
        data=data,
        auth=(cfg["client_id"], cfg["client_secret"]),
        timeout=cfg["timeout_seconds"],
    )
    resp.raise_for_status()
    parsed = resp.json()
    token = parsed.get("access_token")
    if not token:
        raise RuntimeError(f"Token response missing access_token: {parsed}")
    return token


def fetch_temperature(cfg: Dict[str, Any], token: str, verbose: bool = False) -> Dict[str, Any]:
    endpoint = cfg["thermostat_endpoint"]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if verbose:
        print(f"Requesting thermostat status from {endpoint}")
    resp = requests.get(endpoint, headers=headers, timeout=cfg["timeout_seconds"])
    resp.raise_for_status()
    return resp.json()


def extract_temp_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    temp = response.get("current_temperature")
    if temp is None:
        raise RuntimeError("Response does not include current_temperature")
    reading = {
        "current_temperature": temp,
        "target_temperature": response.get("target_temperature"),
        "mode": response.get("mode"),
    }
    return reading


def main() -> None:
    args = parse_args()
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"Unable to load config: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        token = request_token(cfg, verbose=args.verbose)
        payload = fetch_temperature(cfg, token, verbose=args.verbose)
        reading = extract_temp_payload(payload)
    except Exception as exc:
        print(f"Failed to read thermostat temperature: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Seam Thermostat Reading")
    print("------------------------")
    print(f"Current: {reading['current_temperature']}° ({payload.get('reported_at', 'unknown time')})")
    target = reading.get("target_temperature")
    if target is not None:
        print(f"Target : {target}°")
    mode = reading.get("mode")
    if mode:
        print(f"Mode   : {mode}")


if __name__ == "__main__":
    main()
