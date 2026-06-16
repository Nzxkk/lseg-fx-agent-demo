"""LLM-based Reuters/LSEG FX news scoring.

The model only scores already-fetched news. It does not create market data,
headlines, or trading signals.
"""

from __future__ import annotations

import json
import http.client
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List

import pandas as pd

try:
    from .llm_report import _extract_content, _llm_config, _validate_header_value
except ImportError:
    from llm_report import _extract_content, _llm_config, _validate_header_value


def score_news_with_llm(news: pd.DataFrame, batch_size: int = 8) -> pd.DataFrame:
    if news is None or news.empty:
        return news

    config = _llm_config()
    api_url = config["api_url"]
    api_key = config["api_key"]
    model = config["model"]
    if not api_url:
        raise ValueError("新闻大模型评分需要配置 FX_LLM_API_URL，或使用页面里的 Qwen/OpenAI 配置。")
    if not api_key:
        raise ValueError("新闻大模型评分需要 API Key。请在页面的大模型报告设置里填写 Qwen API Key。")
    _validate_header_value("新闻评分 API Key", str(api_key))

    output = news.copy()
    for column in ("usd_score", "eur_score", "jpy_score", "news_confidence", "news_event_type", "news_score_reason"):
        if column not in output.columns:
            output[column] = 0.0 if column.endswith("_score") or column == "news_confidence" else ""

    records = _compact_records(output)
    scored: Dict[int, Dict[str, Any]] = {}
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        for item in _score_batch_with_retry(batch=batch, api_url=str(api_url), api_key=str(api_key), model=model, config=config):
            row_id = int(item.get("row_id", -1))
            if row_id >= 0:
                scored[row_id] = item

    for row_id, item in scored.items():
        if row_id not in output.index:
            continue
        output.at[row_id, "usd_score"] = _clamp_score(item.get("usd_score"))
        output.at[row_id, "eur_score"] = _clamp_score(item.get("eur_score"))
        output.at[row_id, "jpy_score"] = _clamp_score(item.get("jpy_score"))
        output.at[row_id, "news_confidence"] = _clamp_score(item.get("confidence"), lower=0.0, upper=1.0)
        output.at[row_id, "news_event_type"] = str(item.get("event_type") or "macro")
        output.at[row_id, "news_score_reason"] = str(item.get("reason") or "")[:500]
    return output


def _score_batch_with_retry(batch: List[Dict[str, Any]], api_url: str, api_key: str, model: str | None, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return _score_batch(batch=batch, api_url=api_url, api_key=api_key, model=model, config=config)
    except ValueError as exc:
        message = str(exc)
        if "连接被关闭" not in message and "连接被重置" not in message and "超时" not in message:
            raise
        # Retry once with the same compact batch. Some compatible gateways close
        # idle or overloaded connections without a response.
        return _score_batch(batch=batch, api_url=api_url, api_key=api_key, model=model, config=config)


def _compact_records(news: pd.DataFrame) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for row_id, row in news.reset_index(drop=True).iterrows():
        records.append(
            {
                "row_id": int(row_id),
                "timestamp": str(row.get("timestamp") or "")[:32],
                "headline": _trim(row.get("headline"), 260),
                "body": _trim(row.get("body"), 500),
            }
        )
    return records


def _score_batch(batch: List[Dict[str, Any]], api_url: str, api_key: str, model: str | None, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload: Dict[str, Any] = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an FX macro news scorer. Score each Reuters/LSEG news item for immediate directional impact "
                    "on USD, EUR, and JPY. Return only strict JSON. Scores must be numbers from -1 to 1, where positive "
                    "means supportive for that currency and negative means negative for that currency. Do not invent news."
                ),
            },
            {
                "role": "user",
                "content": (
                    "For each item, return a JSON array with objects: row_id, usd_score, eur_score, jpy_score, "
                    "confidence, event_type, reason. Keep reason short Chinese. News items:\n"
                    + json.dumps(batch, ensure_ascii=False)
                ),
            },
        ],
        "temperature": 0.0,
    }
    if model:
        payload["model"] = model

    headers = {"Content-Type": "application/json"}
    auth_header = config.get("auth_header") or "Authorization"
    if str(auth_header).lower() == "api-key":
        headers["api-key"] = api_key
    else:
        headers[str(auth_header)] = "Bearer {}".format(api_key)

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
        raise ValueError("新闻大模型评分失败：HTTP {} {}".format(exc.code, detail[-800:]))
    except urllib.error.URLError as exc:
        raise ValueError("无法连接新闻大模型评分接口：{}".format(exc.reason))
    except http.client.RemoteDisconnected as exc:
        raise ValueError(
            "新闻大模型评分失败：大模型接口连接被关闭，没有返回结果。"
            "请检查 API Key、模型名、接口地址，或先切回“规则评分”确认 LSEG 数据链路。"
        ) from exc
    except (ConnectionResetError, TimeoutError, socket.timeout) as exc:
        raise ValueError(
            "新闻大模型评分失败：大模型接口连接被重置或超时。"
            "请稍后重试，或先切回“规则评分”。"
        ) from exc
    except UnicodeEncodeError as exc:
        raise ValueError("新闻大模型评分失败：API Key 或 Header 中包含中文/非法字符，请只粘贴 API Key 本身。") from exc

    content = _extract_content(json.loads(raw))
    parsed = _parse_json_content(content)
    if not isinstance(parsed, list):
        raise ValueError("新闻大模型评分返回格式不正确：需要 JSON array。")
    return [item for item in parsed if isinstance(item, dict)]


def _parse_json_content(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            raise
        return json.loads(match.group(0))


def _trim(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _clamp_score(value: Any, lower: float = -1.0, upper: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(lower, min(upper, number))
