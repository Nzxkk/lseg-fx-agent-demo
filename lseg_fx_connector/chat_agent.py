"""Chat workflow router for the local FX Vibe Agent page."""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from fx_agent import _load_agent_skills, read_latest_agent_run, run_fx_agent
from llm_report import _extract_content, _llm_config, _validate_header_value, generate_llm_report, read_latest_llm_report


ROOT = Path("/Users/nzxkk/Desktop/vi/Vibe-Trading")
CONNECTOR_DIR = ROOT / "lseg_fx_connector"
OUTPUT_DIR = CONNECTOR_DIR / "output"


def _read_csv_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [_coerce_record(row) for row in csv.DictReader(file)]


def _coerce_record(row: Dict[str, str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in row.items():
        if value == "":
            result[key] = None
            continue
        try:
            result[key] = float(value)
        except (TypeError, ValueError):
            result[key] = value
    return result


def _has_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _history_text(payload: Dict[str, Any]) -> str:
    history = payload.get("chatHistory") or []
    if not isinstance(history, list):
        return ""
    texts = []
    for item in history[-8:]:
        if isinstance(item, dict):
            texts.append(str(item.get("text") or ""))
    return "\n".join(texts).lower()


def _skill_lookup() -> Dict[str, Dict[str, Any]]:
    return {str(skill.get("name")): skill for skill in _load_agent_skills()}


def _skill_refs(names: List[str]) -> List[Dict[str, Any]]:
    lookup = _skill_lookup()
    refs = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        skill = lookup.get(name)
        refs.append(
            {
                "name": name,
                "title": skill.get("title") if skill else name,
                "category": skill.get("category") if skill else "missing",
            }
        )
    return refs


def _classify_intent(message: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    text = message.lower()
    context = "{}\n{}".format(_history_text(payload), text)
    is_continuation = _has_any(text, ["继续", "然后", "下一步"])
    prior_strategy_done = _has_any(context, ["策略和回测已完成", "已完成：策略", "回测已完成"])
    wants_report = _has_any(text, ["报告", "report", "总结"]) or (
        is_continuation and (_has_any(context, ["报告", "report", "总结"]) or prior_strategy_done)
    )
    wants_explain = _has_any(text, ["解释", "为什么", "怎么看", "说明"])
    wants_strategy = _has_any(text, ["策略", "回测", "backtest", "运行", "生成", "agent"]) or (
        _has_any(text, ["信号"]) and not wants_explain
    ) or (is_continuation and not prior_strategy_done and _has_any(context, ["策略", "回测", "信号", "agent"]))
    wants_status = _has_any(text, ["状态", "status", "有没有数据", "输出"])
    wants_skills = _has_any(text, ["skill", "skills", "技能"])

    if wants_skills:
        return {
            "intent": "list_skills",
            "skills": ["research-workflow"],
            "reasoning": "用户询问技能清单，调用 workflow skill 展示本地能力目录。",
        }
    if wants_status:
        return {
            "intent": "status",
            "skills": ["research-workflow", "lseg-session-diagnostics"],
            "reasoning": "用户询问输出状态，需要检查本地 artifacts 和最近 Agent 运行结果。",
        }
    if wants_strategy and wants_report:
        return {
            "intent": "run_agent_then_report",
            "skills": [
                "research-workflow",
                "lseg-session-diagnostics",
                "lseg-fx-market-data",
                "dxy-proxy-construction",
                "reuters-fx-news-policy",
                "fx-factor-weighting",
                "fx-macro-signal-decision",
                "fx-shadow-backtest",
                "fx-agent-risk-review",
                "fx-llm-report-writer",
            ],
            "reasoning": "用户要求从策略生成到回测再到报告，必须串联数据、信号、回测、风控和 LLM 报告 skills。",
        }
    if wants_report:
        return {
            "intent": "generate_report",
            "skills": ["research-workflow", "fx-agent-risk-review", "fx-llm-report-writer"],
            "reasoning": "用户要求报告，报告只能基于已有信号、回测、新闻和风控结果生成。",
        }
    if wants_strategy:
        return {
            "intent": "run_agent",
            "skills": [
                "research-workflow",
                "lseg-session-diagnostics",
                "lseg-fx-market-data",
                "dxy-proxy-construction",
                "reuters-fx-news-policy",
                "fx-factor-weighting",
                "fx-macro-signal-decision",
                "fx-shadow-backtest",
                "fx-agent-risk-review",
            ],
            "reasoning": "用户要求生成策略/信号/回测，调用完整研究链路但不调用 LLM 报告。",
        }
    if wants_explain:
        return {
            "intent": "explain_signals",
            "skills": ["fx-macro-signal-decision", "reuters-fx-news-policy", "fx-agent-risk-review"],
            "reasoning": "用户要求解释，需要读取当前信号、新闻分和风险检查。",
        }
    return {
        "intent": "help",
        "skills": ["research-workflow"],
        "reasoning": "未识别到明确动作，返回可用聊天命令。",
    }


def _classify_with_llm(message: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    config = _llm_config(payload)
    api_url = config.get("api_url")
    api_key = config.get("api_key")
    model = config.get("model")
    if not api_url or not api_key:
        return None
    _validate_header_value("API Key", str(api_key))

    skill_catalog = [
        {
            "name": skill.get("name"),
            "title": skill.get("title"),
            "category": skill.get("category"),
            "description": skill.get("description"),
        }
        for skill in _load_agent_skills()
    ]
    allowed_intents = ["run_agent", "run_agent_then_report", "generate_report", "explain_signals", "status", "list_skills", "help"]
    allowed_profiles = list(STRATEGY_PROFILES)
    request_payload: Dict[str, Any] = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 FX Vibe Agent 的 skill router。你只做路由，不生成行情、不写报告。"
                    "根据用户消息、最近上下文和 skill catalog，选择 intent、skills 和 strategy_profile。"
                    "必须只输出 JSON object。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": message,
                        "recent_context": _history_text(payload),
                        "allowed_intents": allowed_intents,
                        "allowed_strategy_profiles": allowed_profiles,
                        "skill_catalog": skill_catalog,
                        "output_schema": {
                            "intent": "one allowed intent",
                            "skills": ["skill names from catalog"],
                            "strategy_profile": "one allowed profile, or balanced",
                            "reasoning": "short Chinese reason",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.0,
    }
    if model:
        request_payload["model"] = model

    headers = {"Content-Type": "application/json"}
    auth_header = config.get("auth_header") or "Authorization"
    if str(auth_header).lower() == "api-key":
        headers["api-key"] = str(api_key)
    else:
        headers[str(auth_header)] = "Bearer {}".format(api_key)

    request = urllib.request.Request(
        str(api_url),
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError):
        return None

    try:
        parsed = _parse_json_content(_extract_content(json.loads(raw)))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None

    intent = str(parsed.get("intent") or "")
    if intent not in allowed_intents:
        return None
    valid_skills = {str(skill.get("name")) for skill in skill_catalog}
    skills = [str(name) for name in parsed.get("skills") or [] if str(name) in valid_skills]
    if not skills:
        fallback = _classify_intent(message, payload)
        skills = fallback.get("skills", [])
    profile = str(parsed.get("strategy_profile") or "balanced")
    if profile not in STRATEGY_PROFILES:
        profile = "balanced"
    return {
        "intent": intent,
        "skills": skills,
        "strategy_profile": profile,
        "reasoning": "Qwen skill router：{}".format(str(parsed.get("reasoning") or "根据任务目标匹配 skills。")[:500]),
        "router": "llm",
    }


def _parse_json_content(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise
        return json.loads(match.group(0))


def _with_skill_context(result: Dict[str, Any], route: Dict[str, Any]) -> Dict[str, Any]:
    result["intent"] = route.get("intent")
    result["used_skills"] = _skill_refs(route.get("skills", []))
    result["skill_reasoning"] = route.get("reasoning")
    result["skill_router"] = route.get("router", "rules")
    return result


STRATEGY_PROFILES: Dict[str, Dict[str, Any]] = {
    "eurusd_trend_pullback": {
        "label": "EUR/USD 趋势回调策略",
        "trendWeight": 70,
        "carryWeight": 5,
        "dollarWeight": 10,
        "newsWeight": 5,
        "riskWeight": 10,
        "scoreThreshold": 0.30,
        "ruleStrategy": "eurusd_trend_pullback",
        "description": "只对 EUR/USD 启用长期趋势过滤 + 短期回调/反弹结束规则；USD/JPY 和 DXY_PROXY 仍使用多因子信号。",
    },
    "balanced": {
        "label": "均衡策略",
        "trendWeight": 30,
        "carryWeight": 25,
        "dollarWeight": 20,
        "newsWeight": 15,
        "riskWeight": 10,
        "scoreThreshold": 0.35,
        "ruleStrategy": "factor_blend",
        "description": "使用页面默认的均衡因子配置。",
    },
    "trend": {
        "label": "趋势策略",
        "trendWeight": 55,
        "carryWeight": 10,
        "dollarWeight": 20,
        "newsWeight": 5,
        "riskWeight": 10,
        "scoreThreshold": 0.32,
        "ruleStrategy": "factor_blend",
        "description": "更重视 20/60 日价格动量，新闻和利差只做辅助。",
    },
    "carry": {
        "label": "利差/政策策略",
        "trendWeight": 15,
        "carryWeight": 55,
        "dollarWeight": 10,
        "newsWeight": 10,
        "riskWeight": 10,
        "scoreThreshold": 0.34,
        "ruleStrategy": "factor_blend",
        "description": "更重视政策利率和 10Y 收益率差异。",
    },
    "news": {
        "label": "新闻事件策略",
        "trendWeight": 15,
        "carryWeight": 10,
        "dollarWeight": 10,
        "newsWeight": 55,
        "riskWeight": 10,
        "scoreThreshold": 0.30,
        "ruleStrategy": "factor_blend",
        "description": "更重视 Reuters/LSEG 宏观新闻和央行事件分。",
    },
    "dollar": {
        "label": "美元周期策略",
        "trendWeight": 20,
        "carryWeight": 15,
        "dollarWeight": 50,
        "newsWeight": 5,
        "riskWeight": 10,
        "scoreThreshold": 0.33,
        "ruleStrategy": "factor_blend",
        "description": "更重视 DXY/DXY_PROXY 的美元周期确认。",
    },
    "defensive": {
        "label": "保守防守策略",
        "trendWeight": 20,
        "carryWeight": 20,
        "dollarWeight": 15,
        "newsWeight": 10,
        "riskWeight": 35,
        "scoreThreshold": 0.48,
        "ruleStrategy": "factor_blend",
        "description": "提高交易阈值，更重视风险情绪，减少交易次数。",
    },
    "aggressive": {
        "label": "激进交易策略",
        "trendWeight": 40,
        "carryWeight": 20,
        "dollarWeight": 20,
        "newsWeight": 15,
        "riskWeight": 5,
        "scoreThreshold": 0.22,
        "ruleStrategy": "factor_blend",
        "description": "降低交易阈值，更容易触发 LONG/SHORT。",
    },
}


def _infer_strategy_profile(message: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    text = "{}\n{}".format(_history_text(payload), message.lower())
    if str(payload.get("llmStrategyProfile") or "") in STRATEGY_PROFILES:
        name = str(payload.get("llmStrategyProfile"))
    elif (
        _has_any(text, ["eur/usd", "eurusd", "欧元美元"])
        and _has_any(text, ["长期上升", "长期上涨", "长期下降", "长期下跌", "长期趋势"])
        and _has_any(text, ["短期回调", "回调结束", "短期反弹", "反弹结束"])
        and _has_any(text, ["买入", "做多", "做空", "short", "long"])
    ):
        name = "eurusd_trend_pullback"
    elif _has_any(text, ["趋势", "动量", "momentum", "trend"]):
        name = "trend"
    elif _has_any(text, ["carry", "利差", "息差", "套息", "政策", "央行"]):
        name = "carry"
    elif _has_any(text, ["新闻", "事件", "news", "reuters", "headline", "宏观事件"]):
        name = "news"
    elif _has_any(text, ["美元", "dxy", "dollar", "美指"]):
        name = "dollar"
    elif _has_any(text, ["保守", "防守", "稳健", "低风险", "少交易"]):
        name = "defensive"
    elif _has_any(text, ["激进", "高频", "多交易", "进攻", "aggressive"]):
        name = "aggressive"
    elif _has_any(text, ["换一个", "不一样", "另一个", "不同"]):
        name = "news"
    else:
        name = str(payload.get("strategyProfile") or "balanced")
        if name not in STRATEGY_PROFILES:
            name = "balanced"
    profile = dict(STRATEGY_PROFILES[name])
    profile["name"] = name
    return profile


def _apply_strategy_profile(message: str, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    profile = _infer_strategy_profile(message, payload)
    params = dict(payload)
    for key in ("trendWeight", "carryWeight", "dollarWeight", "newsWeight", "riskWeight", "scoreThreshold"):
        params[key] = profile[key]
    params["ruleStrategy"] = profile.get("ruleStrategy", "factor_blend")
    params["strategyProfile"] = profile["name"]
    params["strategyLabel"] = profile["label"]
    params["strategyDescription"] = profile["description"]
    return params, profile


def _status_reply() -> Dict[str, Any]:
    signals = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signals.csv")
    summary = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_backtest_summary.csv")
    news = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_news.csv")
    agent = read_latest_agent_run()
    lines = [
        "当前本地输出状态：",
        "- 最新信号：{} 行".format(len(signals)),
        "- 回测摘要：{} 行".format(len(summary)),
        "- 新闻：{} 行".format(len(news)),
        "- Agent 最近运行：{}".format("成功" if agent.get("ok") else "暂无或失败"),
    ]
    return {"reply": "\n".join(lines), "refresh": True}


def _skills_reply() -> Dict[str, Any]:
    skills = _load_agent_skills()
    lines = ["当前可用 skills："]
    for skill in skills:
        lines.append("- {} [{}]：{}".format(skill.get("name"), skill.get("category"), skill.get("title")))
    return {"reply": "\n".join(lines), "skills": skills, "refresh": True}


def _signals_reply() -> Dict[str, Any]:
    signals = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signals.csv")
    if not signals:
        return {"reply": "当前没有信号文件。你可以输入“生成外汇策略并回测”，我会调用 Agent 拉取真实 LSEG 数据。", "refresh": True}
    lines = ["当前最新信号："]
    for row in signals:
        lines.append(
            "- {instrument}: {side}, 分数 {score:.3f}, 置信度 {confidence:.3f}".format(
                instrument=row.get("instrument") or "N/A",
                side=row.get("side") or "HOLD",
                score=float(row.get("composite_score") or 0.0),
                confidence=float(row.get("confidence") or 0.0),
            )
        )
    return {"reply": "\n".join(lines), "signals": signals, "refresh": True}


def _clean_error_message(error: Any) -> str:
    text = str(error or "").strip()
    if not text:
        return "Agent 运行失败。"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    traceback_lines = [
        line
        for line in lines
        if line.startswith(("ValueError:", "RuntimeError:", "UnicodeEncodeError:", "HTTPError:", "http.client.RemoteDisconnected:"))
    ]
    if traceback_lines:
        return traceback_lines[-1]
    return lines[-1] if lines else text[:800]


def _run_agent_from_chat(message: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    objective = message or payload.get("objective")
    params, profile = _apply_strategy_profile(message, payload)
    if str(params.get("newsScoreMode") or "rule") == "llm" and not (
        params.get("llmApiKey")
        or os.getenv("FX_LLM_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("QWEN_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        return {
            "reply": "已选择大模型新闻评分，但还没有 API Key。请展开“大模型报告设置”，填写 Qwen API Key 后再运行。",
            "strategy_profile": profile,
            "refresh": True,
        }
    result = run_fx_agent(
        objective=str(objective),
        start=params.get("start"),
        end=params.get("end"),
        params=params,
    )
    if result.get("ok"):
        lines = [
            "已完成：策略信号、影子回测、Agent 决策和风控检查。",
            "本次策略：{}。{}".format(profile["label"], profile["description"]),
            "权重：趋势 {trendWeight} / 利差政策 {carryWeight} / 美元周期 {dollarWeight} / 新闻 {newsWeight} / 风险 {riskWeight}；阈值 {scoreThreshold}".format(
                **profile
            ),
            "规则：{}".format(
                "EUR/USD 长期趋势 + 短期回调/反弹结束"
                if profile.get("ruleStrategy") == "eurusd_trend_pullback"
                else "多因子合成"
            ),
        ]
        for decision in result.get("decisions", []):
            lines.append(
                "- {instrument}: {decision}, {side}, 分数 {score:.3f}".format(
                    instrument=decision.get("instrument"),
                    decision=decision.get("decision"),
                    side=decision.get("side"),
                    score=float(decision.get("score") or 0.0),
                )
            )
        return {"reply": "\n".join(lines), "agent": result, "strategy_profile": profile, "refresh": True}

    failed = next((step for step in result.get("steps", []) if step.get("status") == "error"), {})
    error = _clean_error_message(failed.get("error") or "Agent 运行失败。")
    return {
        "reply": "Agent 没有完成，原因：{}\n如果你启用了“大模型新闻评分”，请确认 API Key 输入框里只有 Key 本身，不要带中文说明或多余文字。".format(
            str(error)[:800]
        ),
        "agent": result,
        "strategy_profile": profile,
        "refresh": True,
    }


def _generate_report_from_chat(message: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    existing = read_latest_llm_report()
    if not _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signals.csv"):
        return {"reply": "还没有可用信号。请先输入“生成外汇策略并回测”，或点击“运行 Agent”。", "refresh": True}
    if not payload.get("llmApiKey") and not existing:
        return {
            "reply": "可以生成报告，但需要先在页面填写 Qwen / DashScope API Key。Key 只用于这次本地请求，不写入文件。",
            "refresh": True,
        }
    if payload.get("llmApiKey"):
        result = generate_llm_report(objective=message, llm_options=payload)
        return {"reply": "大模型中文报告已生成。你可以在“大模型中文报告”区域查看。", "llm_report": result, "refresh": True}
    return {"reply": "已找到上一次大模型报告，页面已刷新显示。", "refresh": True}


def _run_agent_then_report(message: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    agent_result = _run_agent_from_chat(message, payload)
    if not agent_result.get("agent", {}).get("ok"):
        return agent_result
    if not payload.get("llmApiKey"):
        agent_result["reply"] += "\n\n策略和回测已完成。要生成大模型中文报告，请在页面填写 Qwen API Key 后再说“生成中文报告”。"
        return agent_result
    report_result = _generate_report_from_chat(message, payload)
    agent_result["reply"] += "\n\n" + report_result.get("reply", "")
    agent_result["llm_report"] = report_result.get("llm_report")
    agent_result["refresh"] = True
    return agent_result


def handle_chat(message: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    text = message.strip()
    if not text:
        return {"reply": "请输入你要做的事，例如：生成外汇策略并回测，或者生成中文报告。"}
    route = _classify_with_llm(text, payload) or _classify_intent(text, payload)
    payload = dict(payload)
    if route.get("strategy_profile"):
        payload["llmStrategyProfile"] = route.get("strategy_profile")
    intent = route["intent"]
    if intent == "list_skills":
        return _with_skill_context(_skills_reply(), route)
    if intent == "status":
        return _with_skill_context(_status_reply(), route)
    if intent == "run_agent_then_report":
        return _with_skill_context(_run_agent_then_report(text, payload), route)
    if intent == "generate_report":
        return _with_skill_context(_generate_report_from_chat(text, payload), route)
    if intent == "run_agent":
        return _with_skill_context(_run_agent_from_chat(text, payload), route)
    if intent == "explain_signals":
        return _with_skill_context(_signals_reply(), route)

    return _with_skill_context(
        {
            "reply": (
                "我可以通过聊天帮你做这些事：\n"
                "- “生成外汇策略并回测”\n"
                "- “生成中文报告”\n"
                "- “解释当前信号”\n"
                "- “查看状态”"
            ),
            "refresh": True,
        },
        route,
    )
