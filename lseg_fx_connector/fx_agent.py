"""Lightweight FX agent for the LSEG signal console.

The agent is intentionally deterministic: it orchestrates data collection,
signal generation, output loading, and a readable summary. It does not invent
market data and fails clearly when LSEG/Refinitiv is unavailable.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from .fx_lseg_data import (
        fetch_lseg_market_data,
        fetch_lseg_reuters_news,
        load_policy_rates,
        load_ric_map,
    )
    from .fx_macro_news_demo import (
        SignalConfig,
        _backtest_summary,
        _generate_signal_history,
        _normalize_weights,
        _shadow_backtest,
        build_business_report,
        generate_trade_signals,
        load_market_data,
        load_reuters_export,
        prepare_news_output,
    )
    from .news_llm_score import score_news_with_llm
except ImportError:
    from fx_lseg_data import (
        fetch_lseg_market_data,
        fetch_lseg_reuters_news,
        load_policy_rates,
        load_ric_map,
    )
    from fx_macro_news_demo import (
        SignalConfig,
        _backtest_summary,
        _generate_signal_history,
        _normalize_weights,
        _shadow_backtest,
        build_business_report,
        generate_trade_signals,
        load_market_data,
        load_reuters_export,
        prepare_news_output,
    )
    from news_llm_score import score_news_with_llm


CONNECTOR_DIR = Path(__file__).resolve().parent
ROOT = CONNECTOR_DIR.parent
OUTPUT_DIR = CONNECTOR_DIR / "output"
SKILL_DIR = CONNECTOR_DIR / "fx_agent_skills"

AGENT_RUN_PATH = OUTPUT_DIR / "fx_agent_run.json"
AGENT_REPORT_PATH = OUTPUT_DIR / "fx_agent_report.md"


def _optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _build_signal_command(
    start: Optional[str],
    end: Optional[str],
    params: Dict[str, Any],
    python_bin: Optional[str] = None,
) -> List[str]:
    cmd = [
        python_bin or sys.executable,
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
    return cmd


def _subprocess_env(params: Dict[str, Any]) -> Dict[str, str]:
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


def _redact_params(params: Dict[str, Any]) -> Dict[str, Any]:
    safe = dict(params)
    if safe.get("llmApiKey"):
        safe["llmApiKey"] = "***"
    return safe


def _run_step(name: str, description: str, func) -> Dict[str, Any]:
    started = time.time()
    try:
        output = func()
        return {
            "name": name,
            "description": description,
            "status": "ok",
            "duration_seconds": round(time.time() - started, 3),
            "output": output,
        }
    except Exception as exc:  # noqa: BLE001 - user-facing orchestration boundary
        return {
            "name": name,
            "description": description,
            "status": "error",
            "duration_seconds": round(time.time() - started, 3),
            "error": str(exc),
        }


def _load_agent_skills() -> List[Dict[str, str]]:
    skills: List[Dict[str, str]] = []
    if not SKILL_DIR.exists():
        return skills
    for path in sorted(SKILL_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        metadata, body = _parse_skill_markdown(text)
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        title = lines[0].lstrip("# ").strip() if lines else metadata.get("name", path.stem)
        description = metadata.get("description") or " ".join(line.lstrip("- ").strip() for line in lines[1:4])
        skills.append(
            {
                "name": metadata.get("name", path.stem),
                "title": title,
                "description": description,
                "category": metadata.get("category", "fx-agent"),
                "path": str(path),
            }
        )
    return skills


def _parse_skill_markdown(text: str) -> tuple[Dict[str, str], str]:
    metadata: Dict[str, str] = {}
    if not text.startswith("---"):
        return metadata, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return metadata, text
    frontmatter = parts[1]
    body = parts[2].strip()
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata, body


def _skill_by_name(skills: List[Dict[str, str]], name: str) -> Dict[str, str]:
    return next((skill for skill in skills if skill.get("name") == name), {"name": name, "title": name, "category": "missing", "description": ""})


SKILL_STEP_MAPPING = [
        ("理解任务", "research-workflow", "确认目标、标的范围、研究边界和输出标准。"),
        ("加载 Skills", "research-workflow", "读取本地 skill 文档并建立可追踪的执行计划。"),
        ("选择 Skills", "research-workflow", "根据任务、聊天路由和页面设置选择本次真正参与执行的 skill。"),
        ("会话诊断", "lseg-session-diagnostics", "区分 Python 包、Workspace 会话、桌面代理、RIC 权限和新闻权限问题。"),
        ("生成行情", "lseg-fx-market-data", "拉取 LSEG/Refinitiv 行情并校验核心 RIC。"),
        ("DXY 处理", "dxy-proxy-construction", "直连 DXY 不可用时，用六个外汇成分构造 DXY_PROXY。"),
        ("生成新闻", "reuters-fx-news-policy", "拉取 Reuters/LSEG 新闻并转换为可解释的 USD/EUR/JPY 事件分。"),
        ("手动权重", "fx-factor-weighting", "应用页面里的因子权重和交易阈值，作为情景参数而不是改写原始数据。"),
        ("生成信号", "fx-macro-signal-decision", "合成趋势、利差/政策、美元周期、新闻和风险因子。"),
        ("影子回测", "fx-shadow-backtest", "用历史信号和市场收益生成净值、回撤和摘要指标。"),
        ("风控复核", "fx-agent-risk-review", "检查数据完整性、新闻覆盖、仓位约束和影子回测。"),
        ("大模型报告", "fx-llm-report-writer", "基于已计算结果写中文报告，不生成行情或信号。"),
        ("整理结果", "fx-agent-risk-review", "输出交易候选、观察项、风险提示和中文报告。"),
]


def _ordered_skill_names(names: List[str]) -> List[str]:
    ordered = []
    available_order = [skill_name for _, skill_name, _ in SKILL_STEP_MAPPING]
    available_order.extend(name for name in names if name not in available_order)
    name_set = {name for name in names if name}
    for name in available_order:
        if name in name_set and name not in ordered:
            ordered.append(name)
    return ordered


def _select_skill_names(objective: str, params: Dict[str, Any]) -> List[str]:
    requested = params.get("requestedSkills") or []
    if isinstance(requested, str):
        requested_names = [item.strip() for item in requested.split(",") if item.strip()]
    elif isinstance(requested, list):
        requested_names = [str(item) for item in requested if item]
    else:
        requested_names = []

    names = [
        "research-workflow",
        "lseg-session-diagnostics",
        "lseg-fx-market-data",
        "dxy-proxy-construction",
        "reuters-fx-news-policy",
        "fx-macro-signal-decision",
        "fx-shadow-backtest",
        "fx-agent-risk-review",
    ]
    if requested_names:
        names.extend(requested_names)
    if params.get("ruleStrategy") == "eurusd_trend_pullback" or any(
        params.get(key) is not None
        for key in ("trendWeight", "carryWeight", "dollarWeight", "newsWeight", "riskWeight", "scoreThreshold")
    ):
        names.append("fx-factor-weighting")
    objective_text = str(objective or "").lower()
    if params.get("llmApiKey") or "报告" in objective_text or "report" in objective_text:
        names.append("fx-llm-report-writer")
    return _ordered_skill_names(names)


def _skill_excerpt(path: str, limit: int = 1200) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    _, body = _parse_skill_markdown(text)
    useful_lines = []
    for line in body.splitlines():
        clean = line.strip()
        if not clean:
            continue
        useful_lines.append(clean)
        if len("\n".join(useful_lines)) >= limit:
            break
    return "\n".join(useful_lines)[:limit]


def _build_active_skill_context(skills: List[Dict[str, str]], selected_names: List[str]) -> List[Dict[str, Any]]:
    contexts = []
    for name in selected_names:
        skill = _skill_by_name(skills, name)
        if skill.get("category") == "missing":
            contexts.append(
                {
                    "name": name,
                    "title": name,
                    "category": "missing",
                    "used": False,
                    "usage": "本地 skill 文档缺失，不能参与执行。",
                    "instruction_excerpt": "",
                }
            )
            continue
        contexts.append(
            {
                "name": skill.get("name"),
                "title": skill.get("title"),
                "category": skill.get("category"),
                "path": skill.get("path"),
                "used": True,
                "usage": "已读取该 skill markdown，并用于本次 Agent 执行计划、参数解释和报告约束。",
                "instruction_excerpt": _skill_excerpt(str(skill.get("path") or "")),
            }
        )
    return contexts


def _build_skill_plan(skills: List[Dict[str, str]], selected_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    selected = set(selected_names or [])
    plan = []
    for step, skill_name, purpose in SKILL_STEP_MAPPING:
        if selected and skill_name not in selected:
            continue
        skill = _skill_by_name(skills, skill_name)
        plan.append(
            {
                "step": step,
                "skill": skill.get("name"),
                "title": skill.get("title"),
                "category": skill.get("category"),
                "purpose": purpose,
                "invoked": skill_name in selected if selected else True,
                "available": skill.get("category") != "missing",
            }
        )
    return plan


def _run_signal_engine(start: Optional[str], end: Optional[str], params: Dict[str, Any]) -> Dict[str, Any]:
    cmd = _build_signal_command(start=start, end=end, params=params)
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


def _signal_config(params: Dict[str, Any]) -> SignalConfig:
    return SignalConfig(
        trend_weight=_optional_float(params.get("trendWeight")) or 30.0,
        carry_weight=_optional_float(params.get("carryWeight")) or 25.0,
        dollar_weight=_optional_float(params.get("dollarWeight")) or 20.0,
        news_weight=_optional_float(params.get("newsWeight")) or 15.0,
        risk_weight=_optional_float(params.get("riskWeight")) or 10.0,
        score_threshold=_optional_float(params.get("scoreThreshold")) or 0.35,
        rule_strategy=str(params.get("ruleStrategy") or "factor_blend"),
        news_score_mode=str(params.get("newsScoreMode") or "rule"),
    )


def _dataframe_preview(frame: Any, rows: int = 3) -> List[Dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    preview = frame.head(rows).reset_index()
    records = preview.to_dict(orient="records")
    return json.loads(json.dumps(records, default=str, ensure_ascii=False))


def _write_demo_outputs(context: Dict[str, Any]) -> Dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    signals = context.get("signals")
    history = context.get("history")
    backtest = context.get("backtest")
    summary = context.get("summary")
    news_output = context.get("news_output")
    report = context.get("business_report") or ""
    if signals is not None:
        signals.to_csv(OUTPUT_DIR / "fx_macro_news_demo_signals.csv", index=False)
    if history is not None:
        history.to_csv(OUTPUT_DIR / "fx_macro_news_demo_signal_history.csv", index=False)
    if backtest is not None:
        backtest.to_csv(OUTPUT_DIR / "fx_macro_news_demo_shadow_backtest.csv", index=False)
    if summary is not None:
        summary.to_csv(OUTPUT_DIR / "fx_macro_news_demo_backtest_summary.csv", index=False)
    if news_output is not None:
        news_output.to_csv(OUTPUT_DIR / "fx_macro_news_demo_news.csv", index=False)
    (OUTPUT_DIR / "fx_macro_news_demo_report.md").write_text(report, encoding="utf-8")
    return {
        "signals_path": str(OUTPUT_DIR / "fx_macro_news_demo_signals.csv"),
        "backtest_path": str(OUTPUT_DIR / "fx_macro_news_demo_shadow_backtest.csv"),
        "news_path": str(OUTPUT_DIR / "fx_macro_news_demo_news.csv"),
        "report_path": str(OUTPUT_DIR / "fx_macro_news_demo_report.md"),
    }


def _skill_research_workflow(context: Dict[str, Any]) -> Dict[str, Any]:
    context["execution_mode"] = "skill_registry"
    return {
        "objective": context.get("objective"),
        "selected_skills": context.get("selected_skill_names", []),
        "output_standard": "signals + shadow backtest + risk checks + Chinese report",
    }


def _skill_session_diagnostics(context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import lseg.data as _rd  # noqa: F401

        library = "lseg.data"
    except ImportError:
        try:
            import refinitiv.data as _rd  # noqa: F401

            library = "refinitiv.data"
        except ImportError as exc:
            raise RuntimeError("未安装 lseg-data/refinitiv.data，无法通过 LSEG Data Library 拉取真实数据。") from exc
    context["lseg_library"] = library
    return {
        "library": library,
        "note": "Python 数据包存在；Workspace 会话和权限会在行情/新闻 skill 中实际验证。",
    }


def _skill_market_data(context: Dict[str, Any]) -> Dict[str, Any]:
    params = context["params"]
    start = context.get("start") or "2025-01-01"
    end = context.get("end")
    if params.get("marketDataPath"):
        market = load_market_data(params.get("marketDataPath"))
        source = "CSV 行情"
    else:
        market = fetch_lseg_market_data(
            start=start,
            end=end or __import__("datetime").date.today().isoformat(),
            ric_map=load_ric_map(CONNECTOR_DIR / "lseg_ric_map.json"),
            policy_rates=load_policy_rates(CONNECTOR_DIR / "policy_rates.json"),
        )
        source = "LSEG/Refinitiv 行情"
    context["market"] = market
    context["market_source"] = source
    return {
        "source": source,
        "rows": int(len(market)),
        "columns": list(market.columns),
        "start": str(market.index.min().date()) if len(market) else None,
        "end": str(market.index.max().date()) if len(market) else None,
        "preview": _dataframe_preview(market),
    }


def _skill_dxy_proxy(context: Dict[str, Any]) -> Dict[str, Any]:
    market = context.get("market")
    if market is None:
        raise RuntimeError("DXY 处理需要先执行行情 skill。")
    dxy_column = "DXY" if "DXY" in market.columns else "DXY_PROXY"
    usable = market[dxy_column].dropna() if dxy_column in market else []
    if len(usable) == 0:
        raise RuntimeError("DXY/DXY_PROXY 没有可用数据。")
    context["dxy_column"] = dxy_column
    return {
        "dxy_column": dxy_column,
        "latest": float(usable.iloc[-1]),
        "note": "直连 DXY 缺失时，行情 skill 已调用 DXY proxy 构造逻辑。",
    }


def _skill_news_policy(context: Dict[str, Any]) -> Dict[str, Any]:
    params = context["params"]
    if params.get("newsPath"):
        news = load_reuters_export(params.get("newsPath"))
        source = "Reuters 新闻 CSV"
    else:
        news = fetch_lseg_reuters_news(
            "Reuters AND (EUR/USD OR USD/JPY OR DXY OR Fed OR ECB OR BOJ OR inflation OR payrolls)",
            count=100,
        )
        source = "LSEG/Reuters 新闻"
    if context.get("config").news_score_mode == "llm":
        news = score_news_with_llm(news)
        source = "{} + 大模型评分".format(source)
    context["news"] = news
    context["news_source"] = source
    return {
        "source": source,
        "rows": int(len(news)),
        "columns": list(news.columns),
        "preview": _dataframe_preview(news),
    }


def _skill_factor_weighting(context: Dict[str, Any]) -> Dict[str, Any]:
    config = context["config"]
    weights = _normalize_weights(config)
    context["normalized_weights"] = weights
    return {
        "rule_strategy": config.rule_strategy,
        "news_score_mode": config.news_score_mode,
        "score_threshold": config.score_threshold,
        "normalized_weights": weights,
    }


def _skill_signal_decision(context: Dict[str, Any]) -> Dict[str, Any]:
    market = context.get("market")
    news = context.get("news")
    if market is None:
        raise RuntimeError("生成信号需要先执行行情 skill。")
    if news is None:
        raise RuntimeError("生成信号需要先执行新闻 skill。")
    signals = generate_trade_signals(market, news, context["config"])
    history = _generate_signal_history(market, news, context["config"])
    context["signals"] = signals
    context["history"] = history
    return {
        "signals": _dataframe_preview(signals, rows=5),
        "history_rows": int(len(history)),
    }


def _skill_shadow_backtest(context: Dict[str, Any]) -> Dict[str, Any]:
    market = context.get("market")
    history = context.get("history")
    if market is None or history is None:
        raise RuntimeError("影子回测需要先执行行情和信号 skill。")
    backtest = _shadow_backtest(market, history)
    summary = _backtest_summary(backtest)
    context["backtest"] = backtest
    context["summary"] = summary
    return {
        "summary": _dataframe_preview(summary, rows=1),
        "backtest_rows": int(len(backtest)),
    }


def _skill_risk_review(context: Dict[str, Any]) -> Dict[str, Any]:
    signals = context.get("signals")
    summary = context.get("summary")
    news = context.get("news")
    if signals is None:
        raise RuntimeError("风控复核需要先生成信号。")
    max_weight = 0.0
    if not signals.empty and "target_weight" in signals:
        max_weight = float(signals["target_weight"].abs().max())
    return {
        "signal_rows": int(len(signals)),
        "summary_rows": int(len(summary)) if summary is not None else 0,
        "news_rows": int(len(news)) if news is not None else 0,
        "max_abs_target_weight": max_weight,
        "status": "pass" if len(signals) >= 3 and max_weight <= 1.0 else "watch",
    }


def _skill_llm_report_writer(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "ready",
        "note": "该 skill 绑定报告写作边界；实际大模型报告仍由页面“生成中文报告”按钮触发。",
    }


SKILL_EXECUTORS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "research-workflow": _skill_research_workflow,
    "lseg-session-diagnostics": _skill_session_diagnostics,
    "lseg-fx-market-data": _skill_market_data,
    "dxy-proxy-construction": _skill_dxy_proxy,
    "reuters-fx-news-policy": _skill_news_policy,
    "fx-factor-weighting": _skill_factor_weighting,
    "fx-macro-signal-decision": _skill_signal_decision,
    "fx-shadow-backtest": _skill_shadow_backtest,
    "fx-agent-risk-review": _skill_risk_review,
    "fx-llm-report-writer": _skill_llm_report_writer,
}


def _run_skill_executor(skill_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
    executor = SKILL_EXECUTORS.get(skill_name)
    if executor is None:
        return {"skipped": True, "reason": "该 skill 暂无绑定 executor。"}
    return executor(context)


def _finalize_bound_skill_outputs(context: Dict[str, Any]) -> Dict[str, Any]:
    news = context.get("news")
    signals = context.get("signals")
    summary = context.get("summary")
    if signals is None:
        raise RuntimeError("没有生成信号，无法整理输出。")
    news_output = prepare_news_output(news)
    context["news_output"] = news_output
    report = build_business_report(
        signals,
        summary,
        news_output,
        market_source=context.get("market_source") or "未知行情来源",
        news_source=context.get("news_source") or "未知新闻来源",
    )
    context["business_report"] = report
    artifact_paths = _write_demo_outputs(context)
    return {
        "signals": int(len(signals)),
        "summary": int(len(summary)) if summary is not None else 0,
        "backtest": int(len(context.get("backtest"))) if context.get("backtest") is not None else 0,
        "news": int(len(news_output)),
        "artifacts": artifact_paths,
    }


def _classify_signal(row: Dict[str, Any], threshold: float) -> str:
    side = str(row.get("side") or "HOLD").upper()
    score = _optional_float(row.get("composite_score")) or 0.0
    confidence = _optional_float(row.get("confidence")) or abs(score)
    if side in {"LONG", "SHORT"}:
        return "交易候选"
    if confidence >= threshold * 0.75:
        return "重点观察"
    return "暂不交易"


def _decision_for_signal(row: Dict[str, Any], threshold: float) -> Dict[str, Any]:
    score = _optional_float(row.get("composite_score")) or 0.0
    confidence = _optional_float(row.get("confidence")) or abs(score)
    target_weight = _optional_float(row.get("target_weight")) or 0.0
    side = str(row.get("side") or "HOLD").upper()
    label = _classify_signal(row, threshold)
    if label == "交易候选":
        action = "提交人工复核"
        reason = "总分已经越过交易阈值，方向和目标权重可进入人工确认。"
    elif label == "重点观察":
        action = "加入观察清单"
        reason = "信号接近阈值，但方向强度不足，不建议直接交易。"
    else:
        action = "暂不动作"
        reason = "综合分数没有达到开仓条件。"
    return {
        "instrument": row.get("instrument") or "N/A",
        "side": side,
        "score": round(score, 6),
        "confidence": round(confidence, 6),
        "target_weight": round(target_weight, 6),
        "decision": label,
        "action": action,
        "reason": row.get("rationale") or row.get("signal_state") or reason,
    }


def _build_risk_checks(
    steps: List[Dict[str, Any]],
    signals: List[Dict[str, Any]],
    summary: List[Dict[str, Any]],
    news: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    checks: List[Dict[str, str]] = []
    signal_step = next((step for step in steps if step.get("name") == "生成信号"), {})
    failed_step = next((step for step in steps if step.get("status") == "error"), {})
    engine_output = signal_step.get("output") or {}
    engine_error = str(failed_step.get("error") or signal_step.get("error") or engine_output.get("stderr") or "")
    if "新闻大模型评分" in engine_error or "RemoteDisconnected" in engine_error:
        connection_message = "LSEG 行情/新闻已进入流程，但大模型新闻评分失败。可检查 API Key/模型/接口地址，或改用规则评分。"
    elif signal_step.get("status") == "ok" and signals:
        connection_message = "已通过绑定的行情、新闻、信号和回测 skills 完成 LSEG/Refinitiv 流程。"
    else:
        connection_message = "LSEG/Refinitiv 拉取或某个 skill executor 失败。"
    checks.append(
        {
            "name": "真实数据连接",
            "status": "通过" if signal_step.get("status") == "ok" and signals else "未通过",
            "message": connection_message,
        }
    )
    checks.append(
        {
            "name": "信号完整性",
            "status": "通过" if len(signals) >= 3 else "关注",
            "message": "已读取 {} 个标的信号。".format(len(signals)),
        }
    )
    checks.append(
        {
            "name": "新闻覆盖",
            "status": "通过" if news else "关注",
            "message": "本次读取 {} 条新闻；新闻方向分由本地规则计算，不是 Reuters 直接给出的观点。".format(len(news)),
        }
    )
    max_weight = max([abs(_optional_float(row.get("target_weight")) or 0.0) for row in signals] or [0.0])
    checks.append(
        {
            "name": "仓位约束",
            "status": "通过" if max_weight <= 1.0 else "未通过",
            "message": "最大目标权重为 {:.2f}。".format(max_weight),
        }
    )
    if summary:
        row = summary[0]
        max_drawdown = abs(_optional_float(row.get("max_drawdown")) or 0.0)
        checks.append(
            {
                "name": "影子回测",
                "status": "通过" if max_drawdown <= 0.1 else "关注",
                "message": "最大回撤 {:.2%}，仅用于观察规则表现，不代表未来收益。".format(max_drawdown),
            }
        )
    else:
        checks.append({"name": "影子回测", "status": "关注", "message": "暂无回测摘要。"})
    return checks


def _build_agent_report(
    objective: str,
    start: Optional[str],
    end: Optional[str],
    params: Dict[str, Any],
    steps: List[Dict[str, Any]],
    skills: List[Dict[str, str]],
    skill_plan: List[Dict[str, Any]],
    active_skills: List[Dict[str, Any]],
    signals: List[Dict[str, Any]],
    decisions: List[Dict[str, Any]],
    risk_checks: List[Dict[str, str]],
    summary: List[Dict[str, Any]],
    news: List[Dict[str, Any]],
) -> str:
    threshold = _optional_float(params.get("scoreThreshold")) or 0.35
    lines = [
        "# FX Vibe Agent 运行报告",
        "",
        "## 任务目标",
        objective or "监控 EUR/USD、USD/JPY、DXY_PROXY，并给出真实 LSEG 数据驱动的交易信号。",
        "",
        "## 数据范围",
        "- 开始日期：{}".format(start or "2025-01-01"),
        "- 结束日期：{}".format(end or "当前可用日期"),
        "- 数据来源：LSEG/Refinitiv 行情 + Reuters/LSEG 新闻接口；DXY 不可用时使用六个外汇成分合成 DXY_PROXY。",
        "",
        "## 本次策略参数",
        "- 策略：{}".format(params.get("strategyLabel") or params.get("strategyProfile") or "页面手动参数"),
        "- 说明：{}".format(params.get("strategyDescription") or "使用页面当前因子权重。"),
        "- 规则：{}".format(
            "EUR/USD 长期趋势过滤 + 短期回调/反弹结束"
            if params.get("ruleStrategy") == "eurusd_trend_pullback"
            else "多因子合成"
        ),
        "- 新闻评分：{}".format("大模型评分" if params.get("newsScoreMode") == "llm" else "本地规则评分"),
        "- 权重：趋势 {}，利差/政策 {}，美元周期 {}，新闻 {}，风险 {}，阈值 {}。".format(
            params.get("trendWeight", "N/A"),
            params.get("carryWeight", "N/A"),
            params.get("dollarWeight", "N/A"),
            params.get("newsWeight", "N/A"),
            params.get("riskWeight", "N/A"),
            params.get("scoreThreshold", threshold),
        ),
        "",
        "## Agent 执行步骤",
    ]
    for step in steps:
        status = "完成" if step.get("status") == "ok" else "失败"
        lines.append("- {}：{}。{}".format(step.get("name"), status, step.get("description")))

    lines.extend(["", "## 本次实际调用 Skills"])
    if active_skills:
        for skill in active_skills:
            lines.append(
                "- {} [{}]：{}".format(
                    skill.get("title") or skill.get("name"),
                    skill.get("category") or "N/A",
                    skill.get("usage") or "已参与本次流程。",
                )
            )
    else:
        lines.append("本次没有选出可执行 skill。")

    lines.extend(["", "## Skill 执行计划"])
    if skill_plan:
        for item in skill_plan:
            state = "已调用" if item.get("invoked") else ("可用" if item.get("available") else "缺失")
            lines.append(
                "- {step} -> {title} [{category}]：{state}。{purpose}".format(
                    step=item.get("step"),
                    title=item.get("title") or item.get("skill"),
                    category=item.get("category") or "N/A",
                    state=state,
                    purpose=item.get("purpose") or "",
                )
            )
    else:
        lines.append("未生成 skill 执行计划。")

    lines.extend(["", "## Skill 目录"])
    if skills:
        for skill in skills:
            lines.append("- {} [{}]：{}".format(skill.get("title"), skill.get("category"), skill.get("description")))
    else:
        lines.append("未找到本地 skill 文档。")

    lines.extend(["", "## 最新信号与 Agent 决策"])
    if not signals:
        lines.append("没有读到信号结果。通常是 LSEG 会话未打开、权限不足，或 RIC 没有返回数据。")
    else:
        for decision in decisions:
            lines.append(
                "- {instrument}：{side}，分数 {score:.3f}，置信度 {confidence:.3f}，结论：{decision}，动作：{action}。".format(
                    instrument=decision.get("instrument") or "N/A",
                    side=decision.get("side") or "HOLD",
                    score=_optional_float(decision.get("score")) or 0.0,
                    confidence=_optional_float(decision.get("confidence")) or 0.0,
                    decision=decision.get("decision") or "暂不交易",
                    action=decision.get("action") or "暂不动作",
                )
            )

    lines.extend(["", "## 因子解释"])
    lines.append("Agent 当前把趋势、利差/政策、美元周期、新闻、风险情绪五类信号合成一个总分。")
    lines.append("总分超过正阈值才考虑 LONG，低于负阈值才考虑 SHORT；未超过阈值就是 HOLD。")
    lines.append("你在页面上调的比例会改变五类因子在总分里的占比。")

    lines.extend(["", "## 风控检查"])
    for item in risk_checks:
        lines.append("- {}：{}。{}".format(item.get("name"), item.get("status"), item.get("message")))

    lines.extend(["", "## 影子回测摘要"])
    if summary:
        row = summary[0]
        lines.append(
            "- 总收益：{:.2%}；最大回撤：{:.2%}；Sharpe：{:.2f}；有持仓天数：{}。".format(
                _optional_float(row.get("total_return")) or 0.0,
                _optional_float(row.get("max_drawdown")) or 0.0,
                _optional_float(row.get("sharpe")) or 0.0,
                int(_optional_float(row.get("active_days")) or 0),
            )
        )
        lines.append("- 回测口径：T 日收盘后生成信号，使用 T+1 日收益计算；历史新闻按信号日期截断。")
    else:
        lines.append("暂无回测摘要。")

    lines.extend(["", "## 新闻覆盖"])
    lines.append("- 本次读取新闻：{} 条。".format(len(news)))
    if news[:5]:
        lines.append("- 前几条新闻标题：")
        for item in news[:5]:
            lines.append("  - {}".format(item.get("headline") or "N/A"))

    lines.extend(["", "## 注意事项"])
    lines.append("- 这不是自动下单系统；它只生成交易候选、观察项和解释。")
    lines.append("- 新闻正负分目前由本地规则判断，不是 Reuters API 直接返回的交易观点。")
    lines.append("- 如果业务要正式使用，需要补充权限校验、日志留痕、人工确认、风控限额和模型评估。")
    return "\n".join(lines) + "\n"


def run_fx_agent(
    objective: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = params or {}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    steps: List[Dict[str, Any]] = []

    steps.append(
        _run_step(
            "理解任务",
            "确认目标标的是 EUR/USD、USD/JPY、DXY_PROXY，并使用真实 LSEG/Refinitiv 数据。",
            lambda: {"objective": objective, "start": start, "end": end},
        )
    )
    steps.append(
        _run_step(
            "加载 Skills",
            "读取外汇行情、新闻政策、风险控制和组合决策的本地技能卡片。",
            _load_agent_skills,
        )
    )
    skills = steps[1].get("output") or []
    selected_skill_names = _select_skill_names(objective=objective, params=params)
    active_skills = _build_active_skill_context(skills=skills, selected_names=selected_skill_names)
    skill_plan = _build_skill_plan(skills, selected_skill_names)
    steps.append(
        _run_step(
            "选择 Skills",
            "根据任务目标、聊天路由和页面设置选择本次真正参与执行的 skill。",
            lambda: {
                "selected": selected_skill_names,
                "active_skills": [
                    {
                        "name": item.get("name"),
                        "title": item.get("title"),
                        "category": item.get("category"),
                        "used": item.get("used"),
                        "usage": item.get("usage"),
                    }
                    for item in active_skills
                ],
            },
        )
    )

    context: Dict[str, Any] = {
        "objective": objective,
        "start": start,
        "end": end,
        "params": params,
        "config": _signal_config(params),
        "selected_skill_names": selected_skill_names,
    }
    for plan_item in skill_plan:
        skill_name = str(plan_item.get("skill") or "")
        if plan_item.get("step") in {"理解任务", "加载 Skills", "选择 Skills"}:
            continue
        steps.append(
            _run_step(
                str(plan_item.get("step") or skill_name),
                "调用 skill executor：{}。{}".format(plan_item.get("title") or skill_name, plan_item.get("purpose") or ""),
                lambda skill_name=skill_name: _run_skill_executor(skill_name, context),
            )
        )

    pipeline_ok = all(step.get("status") == "ok" for step in steps)
    if pipeline_ok:
        steps.append(
            _run_step(
                "整理结果",
                "把各 skill 生成的行情、新闻、信号和回测写入页面需要的输出文件。",
                lambda: _finalize_bound_skill_outputs(context),
            )
        )
        pipeline_ok = steps[-1].get("status") == "ok"

    if pipeline_ok:
        signals = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signals.csv")
        summary = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_backtest_summary.csv")
        backtest = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_shadow_backtest.csv")
        news = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_news.csv")
    else:
        signals = []
        summary = []
        backtest = []
        news = []
    threshold = _optional_float(params.get("scoreThreshold")) or 0.35
    decisions = [_decision_for_signal(row, threshold) for row in signals]
    risk_checks = _build_risk_checks(steps=steps, signals=signals, summary=summary, news=news)

    report = _build_agent_report(
        objective=objective,
        start=start,
        end=end,
        params=params,
        steps=steps,
        skills=skills,
        skill_plan=skill_plan,
        active_skills=active_skills,
        signals=signals,
        decisions=decisions,
        risk_checks=risk_checks,
        summary=summary,
        news=news,
    )
    AGENT_REPORT_PATH.write_text(report, encoding="utf-8")

    ok = all(step.get("status") == "ok" for step in steps)
    payload = {
        "run_id": run_id,
        "ok": ok,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": objective,
        "start": start,
        "end": end,
        "params": _redact_params(params),
        "steps": steps,
        "skills": skills,
        "active_skills": active_skills,
        "skill_plan": skill_plan,
        "signals": signals,
        "decisions": decisions,
        "risk_checks": risk_checks,
        "summary": summary,
        "news_count": len(news),
        "artifacts": {
            "agent_run": str(AGENT_RUN_PATH),
            "agent_report": str(AGENT_REPORT_PATH),
            "signals": str(OUTPUT_DIR / "fx_macro_news_demo_signals.csv"),
            "backtest": str(OUTPUT_DIR / "fx_macro_news_demo_shadow_backtest.csv"),
            "news": str(OUTPUT_DIR / "fx_macro_news_demo_news.csv"),
        },
        "report": report,
    }
    AGENT_RUN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_latest_agent_run() -> Dict[str, Any]:
    if not AGENT_RUN_PATH.exists():
        return {}
    return json.loads(AGENT_RUN_PATH.read_text(encoding="utf-8"))
