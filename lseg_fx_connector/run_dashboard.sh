#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/Users/nzxkk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"

cd "$ROOT_DIR"

"$PYTHON_BIN" "$ROOT_DIR/lseg_fx_connector/render_dashboard.py"
