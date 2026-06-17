#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "/Users/nzxkk/opt/anaconda3/bin/python" ]]; then
    PYTHON_BIN="/Users/nzxkk/opt/anaconda3/bin/python"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

cd "$ROOT_DIR"
"$PYTHON_BIN" - <<'PY'
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "lseg_fx_connector"))

from fx_agent import run_fx_agent

result = run_fx_agent(
    objective="监控 EUR/USD、USD/JPY 和 DXY_PROXY，结合真实 LSEG 行情和 Reuters/LSEG 新闻，生成今日外汇交易信号。",
)
print(result["report"])
if not result.get("ok"):
    raise SystemExit(1)
PY
