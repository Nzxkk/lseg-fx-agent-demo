#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

START_DATE="${1:-2025-01-01}"
END_DATE="${2:-$(date +%F)}"

cd "$ROOT_DIR"

"$PYTHON_BIN" "$ROOT_DIR/lseg_fx_connector/check_lseg_session.py"

"$PYTHON_BIN" -m lseg_fx_connector.fx_macro_news_demo \
  --use-lseg \
  --lseg-start "$START_DATE" \
  --lseg-end "$END_DATE" \
  --lseg-ric-map "$ROOT_DIR/lseg_fx_connector/lseg_ric_map.json" \
  --lseg-policy-rates "$ROOT_DIR/lseg_fx_connector/policy_rates.json" \
  --lseg-news-query "Reuters AND (EUR/USD OR USD/JPY OR DXY OR Fed OR ECB OR BOJ OR inflation OR payrolls)" \
  --lseg-news-count 100 \
  --output-dir "$ROOT_DIR/lseg_fx_connector/output"
