#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/nzxkk/Desktop/vi/Vibe-Trading"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "/Users/nzxkk/opt/anaconda3/bin/python" ]]; then
    PYTHON_BIN="/Users/nzxkk/opt/anaconda3/bin/python"
  elif [[ -x "/Users/nzxkk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" ]]; then
    PYTHON_BIN="/Users/nzxkk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

PORT="${1:-8765}"

cd "$ROOT_DIR"
"$PYTHON_BIN" "$ROOT_DIR/lseg_fx_connector/web_app.py" "$PORT"
