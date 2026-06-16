"""Local API server for the LSEG FX signal dashboard.

Uses only the Python standard library for serving HTTP. Data generation still
delegates to the existing demo module.
"""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import csv
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from chat_agent import handle_chat
from fx_agent import _load_agent_skills, read_latest_agent_run, run_fx_agent
from llm_report import generate_llm_report, read_latest_llm_report


ROOT = Path("/Users/nzxkk/Desktop/vi/Vibe-Trading")
CONNECTOR_DIR = ROOT / "lseg_fx_connector"
STATIC_DIR = CONNECTOR_DIR / "static"
OUTPUT_DIR = CONNECTOR_DIR / "output"


def _read_csv_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [_coerce_record(row) for row in csv.DictReader(file)]


def _coerce_record(row: dict) -> dict:
    coerced = {}
    for key, value in row.items():
        if value == "":
            coerced[key] = None
            continue
        try:
            coerced[key] = float(value)
        except (TypeError, ValueError):
            coerced[key] = value
    return coerced


def _read_report() -> str:
    path = OUTPUT_DIR / "fx_macro_news_demo_report.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _json_bytes(payload: dict, status: str = "ok") -> bytes:
    return json.dumps({"status": status, **payload}, ensure_ascii=False).encode("utf-8")


def _optional_float(value: object) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _subprocess_env(params: dict) -> dict:
    env = os.environ.copy()
    env.setdefault("PYTHONWARNINGS", "ignore::UserWarning,ignore::FutureWarning")
    mapping = {
        "llmProvider": "FX_LLM_PROVIDER",
        "llmApiKey": "FX_LLM_API_KEY",
        "llmModel": "FX_LLM_MODEL",
        "llmApiUrl": "FX_LLM_API_URL",
    }
    for payload_key, env_key in mapping.items():
        value = params.get(payload_key)
        if value:
            env[env_key] = str(value)
    return env


def _needs_llm_key(params: dict) -> bool:
    return str(params.get("newsScoreMode") or "rule") == "llm" and not (
        params.get("llmApiKey")
        or os.getenv("FX_LLM_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("QWEN_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )


def _run_demo(start: Optional[str], end: Optional[str], params: Optional[dict] = None) -> dict:
    params = params or {}
    cmd = [
        sys.executable,
        "-m",
        "lseg_fx_connector.fx_macro_news_demo",
        "--output-dir",
        str(OUTPUT_DIR),
        "--score-threshold",
        str(_optional_float(params.get("scoreThreshold")) or 0.35),
    ]
    weight_args = {
        "--trend-weight": "trendWeight",
        "--carry-weight": "carryWeight",
        "--dollar-weight": "dollarWeight",
        "--news-weight": "newsWeight",
        "--risk-weight": "riskWeight",
    }
    for cli_name, payload_name in weight_args.items():
        value = _optional_float(params.get(payload_name))
        if value is not None:
            cmd.extend([cli_name, str(value)])
    rule_strategy = str(params.get("ruleStrategy") or "factor_blend")
    if rule_strategy:
        cmd.extend(["--rule-strategy", rule_strategy])
    news_score_mode = str(params.get("newsScoreMode") or "rule")
    if news_score_mode:
        cmd.extend(["--news-score-mode", news_score_mode])

    cmd.extend(
        [
            "--use-lseg",
            "--lseg-start",
            start or "2025-01-01",
            "--lseg-ric-map",
            str(CONNECTOR_DIR / "lseg_ric_map.json"),
            "--lseg-policy-rates",
            str(CONNECTOR_DIR / "policy_rates.json"),
            "--lseg-news-query",
            "Reuters AND (EUR/USD OR USD/JPY OR DXY OR Fed OR ECB OR BOJ OR inflation OR payrolls)",
            "--lseg-news-count",
            "100",
        ]
    )
    if end:
        cmd.extend(["--lseg-end", end])

    completed = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
        env=_subprocess_env(params),
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
        "command": " ".join(cmd),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LsegFxDashboard/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_static("index.html")
        elif parsed.path.startswith("/static/"):
            self._serve_static(parsed.path.removeprefix("/static/"))
        elif parsed.path == "/api/status":
            self._send_json(
                {
                    "output_dir": str(OUTPUT_DIR),
                    "signals_exists": (OUTPUT_DIR / "fx_macro_news_demo_signals.csv").exists(),
                    "summary_exists": (OUTPUT_DIR / "fx_macro_news_demo_backtest_summary.csv").exists(),
                    "news_exists": (OUTPUT_DIR / "fx_macro_news_demo_news.csv").exists(),
                    "report_exists": (OUTPUT_DIR / "fx_macro_news_demo_report.md").exists(),
                }
            )
        elif parsed.path == "/api/signals":
            self._send_json({"data": _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signals.csv")})
        elif parsed.path == "/api/signal-history":
            self._send_json({"data": _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signal_history.csv")})
        elif parsed.path == "/api/backtest":
            self._send_json({"data": _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_shadow_backtest.csv")})
        elif parsed.path == "/api/summary":
            self._send_json({"data": _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_backtest_summary.csv")})
        elif parsed.path == "/api/report":
            self._send_json({"markdown": _read_report()})
        elif parsed.path == "/api/news":
            self._send_json({"data": _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_news.csv")})
        elif parsed.path == "/api/agent/latest":
            self._send_json({"data": read_latest_agent_run()})
        elif parsed.path == "/api/skills":
            self._send_json({"data": _load_agent_skills()})
        elif parsed.path == "/api/llm-report":
            self._send_json({"markdown": read_latest_llm_report()})
        else:
            self._send_json({"message": "not found"}, status="error", http_status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/generate", "/api/agent/run", "/api/llm-report/generate", "/api/chat"}:
            self._send_json({"message": "not found"}, status="error", http_status=HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}

        if parsed.path == "/api/chat":
            try:
                result = handle_chat(str(payload.get("message") or ""), payload)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status="error", http_status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"result": result})
            return

        if parsed.path == "/api/agent/run":
            if _needs_llm_key(payload):
                self._send_json(
                    {"message": "已选择大模型新闻评分，但未填写 API Key。请在“大模型报告设置”里填写 Qwen API Key。"},
                    status="error",
                    http_status=HTTPStatus.BAD_REQUEST,
                )
                return
            result = run_fx_agent(
                objective=str(payload.get("objective") or ""),
                start=payload.get("start"),
                end=payload.get("end"),
                params=payload,
            )
            self._send_json(
                {"result": result},
                status="ok",
                http_status=HTTPStatus.OK,
            )
            return

        if parsed.path == "/api/llm-report/generate":
            try:
                result = generate_llm_report(
                    objective=str(payload.get("objective") or ""),
                    llm_options=payload,
                )
            except ValueError as exc:
                self._send_json(
                    {"message": str(exc)},
                    status="error",
                    http_status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json({"result": result})
            return

        mode = str(payload.get("mode", "lseg")).lower()
        if mode != "lseg":
            self._send_json(
                {"message": "only LSEG/Refinitiv data is allowed"},
                status="error",
                http_status=HTTPStatus.BAD_REQUEST,
            )
            return
        if _needs_llm_key(payload):
            self._send_json(
                {"message": "已选择大模型新闻评分，但未填写 API Key。请在“大模型报告设置”里填写 Qwen API Key。"},
                status="error",
                http_status=HTTPStatus.BAD_REQUEST,
            )
            return
        result = _run_demo(
            start=payload.get("start"),
            end=payload.get("end"),
            params=payload,
        )
        ok = result["returncode"] == 0
        self._send_json(
            {
                "result": result,
                "signals": _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signals.csv"),
                "news": _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_news.csv"),
            },
            status="ok" if ok else "error",
            http_status=HTTPStatus.OK if ok else HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    def _serve_static(self, relative_path: str) -> None:
        path = (STATIC_DIR / relative_path).resolve()
        if STATIC_DIR.resolve() not in path.parents and path != STATIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(
        self,
        payload: dict,
        status: str = "ok",
        http_status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        data = _json_bytes(payload, status=status)
        self.send_response(http_status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"LSEG FX dashboard running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
