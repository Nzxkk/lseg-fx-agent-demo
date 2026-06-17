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

if [[ $# -lt 1 ]]; then
  echo "Usage: ./lseg_fx_connector/run_lseg_fx_demo_with_csv_news.sh /path/to/reuters_news.csv [start_date] [end_date]"
  exit 2
fi

NEWS_CSV="$1"
START_DATE="${2:-2025-01-01}"
END_DATE="${3:-$(date +%F)}"

cd "$ROOT_DIR"

"$PYTHON_BIN" "$ROOT_DIR/lseg_fx_connector/check_lseg_session.py"

"$PYTHON_BIN" -m lseg_fx_connector.fx_macro_news_demo \
  --use-lseg \
  --lseg-start "$START_DATE" \
  --lseg-end "$END_DATE" \
  --lseg-ric-map "$ROOT_DIR/lseg_fx_connector/lseg_ric_map.json" \
  --lseg-policy-rates "$ROOT_DIR/lseg_fx_connector/policy_rates.json" \
  --reuters-news "$NEWS_CSV" \
  --output-dir "$ROOT_DIR/lseg_fx_connector/output"
