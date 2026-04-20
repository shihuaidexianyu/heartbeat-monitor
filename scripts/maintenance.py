#!/usr/bin/env python3
"""Maintenance mode helper for Heartbeat Monitor."""

import argparse
import sys
from pathlib import Path

import requests
import yaml


def load_config() -> dict:
    path = Path("config/client.yaml").resolve()
    if not path.exists():
        print(f"Error: Client config not found: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def get_server_info(data: dict) -> tuple[str, str]:
    base_url = data.get("server", {}).get("base_url")
    server_id = data.get("server", {}).get("server_id")
    if not base_url:
        print("Error: base_url not found in config/client.yaml")
        sys.exit(1)
    if not server_id:
        print("Error: server_id not found in config/client.yaml")
        sys.exit(1)
    return base_url.rstrip("/"), server_id


def call_api(base_url: str, server_id: str, action: str):
    url = f"{base_url}/nodes/{server_id}/maintenance/{action}"
    print(f"==> {'Entering' if action == 'start' else 'Exiting'} maintenance mode for node: {server_id}")
    print(f"    POST {url}")
    try:
        resp = requests.post(url, timeout=10)
    except requests.RequestException as e:
        print(f"Error: request failed: {e}")
        sys.exit(1)

    if resp.status_code == 200:
        print(f"==> Success: node {server_id} {'is now in MAINTENANCE mode' if action == 'start' else 'has left MAINTENANCE mode'}.")
        print(f"    {resp.text}")
    else:
        print(f"Error: HTTP {resp.status_code}")
        print(f"    {resp.text}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Heartbeat Monitor maintenance mode helper")
    parser.add_argument("action", choices=["enter", "exit"], help="Maintenance action")
    args = parser.parse_args()

    data = load_config()
    base_url, server_id = get_server_info(data)
    action = "start" if args.action == "enter" else "end"
    call_api(base_url, server_id, action)


if __name__ == "__main__":
    main()
