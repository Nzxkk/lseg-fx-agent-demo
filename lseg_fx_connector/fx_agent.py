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
from typing import Any, Dict, List, Optional


ROOT = Path("/Users/nzxkk/Desktop/vi/Vibe-Trading")
CONNECTOR_DIR = ROOT / "lseg_fx_connector"
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


def _build_skill_plan(skills: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    mapping = [
        ("理解任务", "research-workflow", "确认目标、标的范围、研究边界和输出标准。"),
        ("加载 Skills", "research-workflow", "读取本地 skill 文档并建立可追踪的执行计划。"),
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
    plan = []
    for step, skill_name, purpose in mapping:
        skill = _skill_by_name(skills, skill_name)
        plan.append(
            {
                "step": step,
                "skill": skill.get("name"),
                "title": skill.get("title"),
                "category": skill.get("category"),
                "purpose": purpose,
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
    engine_output = signal_step.get("output") or {}
    engine_error = str(signal_step.get("error") or engine_output.get("stderr") or "")
    if "新闻大模型评分" in engine_error or "RemoteDisconnected" in engine_error:
        connection_message = "LSEG 行情/新闻已进入流程，但大模型新闻评分失败。可检查 API Key/模型/接口地址，或改用规则评分。"
    elif engine_output.get("returncode") == 0:
        connection_message = "信号引擎已完成 LSEG/Refinitiv 拉取。"
    else:
        connection_message = "LSEG/Refinitiv 拉取或信号生成失败。"
    checks.append(
        {
            "name": "真实数据连接",
            "status": "通过" if signal_step.get("status") == "ok" and engine_output.get("returncode") == 0 else "未通过",
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

    lines.extend(["", "## Skill 执行计划"])
    if skill_plan:
        for item in skill_plan:
            state = "可用" if item.get("available") else "缺失"
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
    steps.append(
        _run_step(
            "生成信号",
            "调用现有外汇宏观新闻信号引擎，拉取 LSEG 行情和 Reuters/LSEG 新闻。",
            lambda: _run_signal_engine(start=start, end=end, params=params),
        )
    )
    signal_step = steps[-1]
    signal_result = signal_step.get("output") or {}
    if signal_step.get("status") != "ok" or signal_result.get("returncode") != 0:
        signal_step["status"] = "error"
        signal_step["error"] = signal_result.get("stderr") or signal_result.get("stdout") or "signal engine failed"

    engine_ok = signal_step.get("status") == "ok" and signal_result.get("returncode") == 0
    if engine_ok:
        signals = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_signals.csv")
        summary = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_backtest_summary.csv")
        backtest = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_shadow_backtest.csv")
        news = _read_csv_records(OUTPUT_DIR / "fx_macro_news_demo_news.csv")
        if not signals:
            signal_step["status"] = "error"
            signal_step["error"] = (
                "signal engine completed but produced no fx_macro_news_demo_signals.csv rows; "
                "check LSEG data/news permissions and the signal engine output."
            )
    else:
        signals = []
        summary = []
        backtest = []
        news = []
    threshold = _optional_float(params.get("scoreThreshold")) or 0.35
    skills = steps[1].get("output") or []
    skill_plan = _build_skill_plan(skills)
    decisions = [_decision_for_signal(row, threshold) for row in signals]
    risk_checks = _build_risk_checks(steps=steps, signals=signals, summary=summary, news=news)

    steps.append(
        _run_step(
            "整理结果",
            "读取信号、回测摘要、新闻列表，生成交易候选、观察项和中文 Agent 报告。",
            lambda: {
                "signals": len(signals),
                "summary": len(summary),
                "backtest": len(backtest),
                "news": len(news),
                "decisions": len(decisions),
            },
        )
    )

    report = _build_agent_report(
        objective=objective,
        start=start,
        end=end,
        params=params,
        steps=steps,
        skills=skills,
        skill_plan=skill_plan,
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
