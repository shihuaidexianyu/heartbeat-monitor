#!/bin/bash
set -e
cd "$(dirname "$0")"
uv run python scripts/maintenance.py exit
