"""LLM report generation for the FX signal console.

The LLM receives only structured, already-computed data. It is not asked to
create prices, news, backtest results, or trading signals.
"""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path("/Users/nzxkk/Desktop/vi/Vibe-Trading")
CONNECTOR_DIR = ROOT / "lseg_fx_connector"
OUTPUT_DIR = CONNECTOR_DIR / "output"
LLM_REPORT_PATH = OUTPUT_DIR / "fx_macro_news_llm_report.md"
AGENT_RUN_PATH = OUTPUT_DIR / "fx_agent_run.json"


def _read_csv_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [_coerce_record(row) for row in csv.DictReader(file)]


def _coerce_record(row: Dict[str, str]) -> Dict[str, Any]:
    coerced: Dict[str, Any] = {}
    for key, value in row.items():
        if value == "":
            coerced[key] = None
            continue
        try:
            coerced[key] = float(value)
        except (TypeError, ValueError):
            coerced[key] = value
    return coerced


def _trim_text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _compact_news(rows: List[Dict[str, Any]], limit: int = 25) -> List[Dict[str, Any]]:
    compact = []
    for row in rows[:limit]:
        compact.append(
            {
                "date": row.get("date"),
                "timestamp": row.get("timestamp"),
                "topic": row.get("topic"),
                "headline": _trim_text(row.get("headline"), 240),
                "body": _trim_text(row.get("body"), 500),
                "usd_score": row.get("usd_score"),
                "eur_score": row.get("eur_score"),
                "jpy_score": row.get("jpy_score"),
            }
        )
    return compact


def build_report_context(objective: str = "") -> Dict[str, Any]:
    signals = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signals.csv")
    summary = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_backtest_summary.csv")
    news = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_news.csv")
    agent_run: Dict[str, Any] = {}
    if AGENT_RUN_PATH.exists():
        try:
            agent_run = json.loads(AGENT_RUN_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            agent_run = {}
    if not signals:
        raise ValueError("没有可用信号。请先运行 Agent 或点击“拉取真实 LSEG 数据”。")
    return {
        "objective": objective,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "instruments": ["EUR/USD", "USD/JPY", "DXY_PROXY"],
        "signals": signals,
        "agent_decisions": agent_run.get("decisions", []),
        "risk_checks": agent_run.get("risk_checks", []),
        "backtest_summary": summary[:1],
        "news": _compact_news(news),
        "news_count": len(news),
        "data_note": "行情和新闻来自 LSEG/Refinitiv；DXY 不可用时使用成分货币合成 DXY_PROXY。",
    }


def _system_prompt() -> str:
    return (
        "你是外汇交易研究助理。只基于用户提供的结构化数据写中文报告，"
        "不得编造价格、新闻、收益、模型表现或交易结论。"
        "交易信号以 signals 中的 side/composite_score/confidence 为准。"
        "如果数据不足，要明确说明不足。输出面向金融业务人员，清晰、克制、可解释。"
    )


def _user_prompt(context: Dict[str, Any]) -> str:
    return (
        "请根据下面 JSON 生成一份中文外汇交易信号报告。\n"
        "报告结构必须包含：1. 今日结论；2. 分标的解读；3. 新闻与宏观影响；"
        "4. 风险提示；5. 下一步观察。\n"
        "请用自然中文，不要输出 JSON，不要新增未提供的数据。\n\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def _extract_content(response: Dict[str, Any]) -> str:
    choices = response.get("choices")
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            content = "".join(parts)
        if content:
            return str(content).strip()
        text = choices[0].get("text")
        if text:
            return str(text).strip()
    output_text = response.get("output_text")
    if output_text:
        return str(output_text).strip()
    raise ValueError("大模型接口返回了结果，但没有找到报告正文。")


def _llm_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[str]]:
    overrides = overrides or {}
    provider = str(overrides.get("llmProvider") or os.getenv("FX_LLM_PROVIDER") or "qwen").lower()
    api_key = (
        overrides.get("llmApiKey")
        or os.getenv("FX_LLM_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("QWEN_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    api_url = overrides.get("llmApiUrl") or os.getenv("FX_LLM_API_URL")
    model = overrides.get("llmModel") or os.getenv("FX_LLM_MODEL")
    auth_header = overrides.get("llmAuthHeader") or os.getenv("FX_LLM_AUTH_HEADER", "Authorization")

    if not api_url and provider == "qwen":
        api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        model = model or "qwen-plus"
    elif not api_url and api_key:
        api_url = "https://api.openai.com/v1/chat/completions"
    return {
        "api_url": api_url,
        "api_key": _clean_api_key(api_key) if api_key else None,
        "model": str(model) if model else None,
        "auth_header": str(auth_header) if auth_header else "Authorization",
        "provider": provider,
    }


def _clean_api_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    match = re.search(r"(sk-ws-[A-Za-z0-9._-]+|sk-[A-Za-z0-9._-]+)", text)
    return match.group(1) if match else text


def _validate_header_value(label: str, value: str) -> None:
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError("{} 里包含中文或其他非 Header 字符。请只粘贴 API Key 本身，不要带说明文字。".format(label)) from exc


def generate_llm_report(objective: str = "", llm_options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = _llm_config(llm_options)
    api_url = config["api_url"]
    api_key = config["api_key"]
    model = config["model"]
    if not api_url:
        raise ValueError(
            "未配置大模型接口。请在页面填写 Qwen API Key，或设置 FX_LLM_API_URL / DASHSCOPE_API_KEY / OPENAI_API_KEY。"
        )
    if not api_key:
        raise ValueError("未填写大模型 API Key。请在页面填写 Qwen API Key，或设置 DASHSCOPE_API_KEY。")
    if "api.openai.com/v1/chat/completions" in api_url and not model:
        raise ValueError("使用 OpenAI 兼容接口时，请设置 FX_LLM_MODEL。")
    _validate_header_value("API Key", api_key)

    context = build_report_context(objective=objective)
    payload: Dict[str, Any] = {
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(context)},
        ],
        "temperature": 0.2,
    }
    if model:
        payload["model"] = model

    headers = {"Content-Type": "application/json"}
    if api_key:
        auth_header = config["auth_header"] or "Authorization"
        if auth_header.lower() == "api-key":
            headers["api-key"] = api_key
        else:
            headers[auth_header] = "Bearer {}".format(api_key)

    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError("大模型接口请求失败：HTTP {} {}".format(exc.code, detail[-1000:]))
    except urllib.error.URLError as exc:
        raise ValueError("无法连接大模型接口：{}".format(exc.reason))
    except UnicodeEncodeError as exc:
        raise ValueError("大模型接口请求失败：API Key 或 Header 中包含非法字符，请只粘贴 API Key 本身。") from exc

    data = json.loads(raw)
    report = _extract_content(data)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LLM_REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    return {
        "created_at": context["created_at"],
        "api_url": api_url,
        "model": model,
        "provider": config.get("provider"),
        "report": report,
        "report_path": str(LLM_REPORT_PATH),
        "context": context,
    }


def read_latest_llm_report() -> str:
    if not LLM_REPORT_PATH.exists():
        return ""
    return LLM_REPORT_PATH.read_text(encoding="utf-8")
