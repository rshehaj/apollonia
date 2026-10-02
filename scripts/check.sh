#!/usr/bin/env bash
# Quality gate shared by contributors, AI agents and CI.
# Usage: scripts/check.sh [extra pytest args]
set -euo pipefail

cd "$(dirname "$0")/../backend"

echo "==> ruff check";  uv run ruff check .
echo "==> ruff format"; uv run ruff format --check .
echo "==> mypy";        uv run mypy
echo "==> pytest";      uv run pytest "$@"
