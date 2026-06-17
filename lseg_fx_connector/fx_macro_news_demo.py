from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

try:
    from .fx_lseg_data import (
        fetch_lseg_market_data,
        fetch_lseg_reuters_news,
        load_policy_rates,
        load_ric_map,
    )
    from .news_llm_score import score_news_with_llm
except ImportError:
    from fx_lseg_data import (
        fetch_lseg_market_data,
        fetch_lseg_reuters_news,
        load_policy_rates,
        load_ric_map,
    )
    from news_llm_score import score_news_with_llm


WATCHLIST = ["EUR/USD", "USD/JPY", "DXY_PROXY"]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


@dataclass
class SignalConfig:
    trend_weight: float = 30.0
    carry_weight: float = 25.0
    dollar_weight: float = 20.0
    news_weight: float = 15.0
    risk_weight: float = 10.0
    score_threshold: float = 0.35
    demo_notional_usd: float = 1_000_000.0
    rule_strategy: str = "factor_blend"
    news_score_mode: str = "rule"
    execution_lag_days: int = 1


def load_market_data(path: Optional[str | Path] = None) -> pd.DataFrame:
    if path is None:
        raise ValueError("market data CSV is required unless --use-lseg is set")
    frame = pd.read_csv(path)
    if "date" not in frame.columns:
        raise ValueError("market data CSV must include a date column")
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()

    aliases = {
        "eurusd": "EUR/USD",
        "EURUSD": "EUR/USD",
        "usdjpy": "USD/JPY",
        "USDJPY": "USD/JPY",
        "dxy": "DXY",
        "DXY_PROXY": "DXY",
    }
    frame = frame.rename(columns={col: aliases.get(col, col) for col in frame.columns})
    required = ["EUR/USD", "USD/JPY", "DXY"]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError("market data CSV missing columns: {}".format(missing))
    for col in frame.columns:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.ffill().dropna(subset=required)


def load_reuters_export(path: Optional[str | Path] = None) -> pd.DataFrame:
    if path is None:
        raise ValueError("Reuters/news CSV is required unless --use-lseg is set")
    frame = pd.read_csv(path)
    if "timestamp" not in frame.columns:
        raise ValueError("Reuters/news CSV must include a timestamp column")
    if "headline" not in frame.columns:
        raise ValueError("Reuters/news CSV must include a headline column")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"]).dt.tz_localize(None)
    if "body" not in frame.columns:
        frame["body"] = ""
    if "topic" not in frame.columns:
        frame["topic"] = "reuters_fx_macro"
    return frame.sort_values("timestamp").reset_index(drop=True)


def score_news(news: pd.DataFrame) -> Dict[str, float]:
    if news is None or news.empty:
        return {"USD": 0.0, "EUR": 0.0, "JPY": 0.0}

    override_cols = {"USD": "usd_score", "EUR": "eur_score", "JPY": "jpy_score"}
    if any(col in news.columns for col in override_cols.values()):
        scores = {}
        for asset, col in override_cols.items():
            if col in news.columns:
                mean_score = pd.to_numeric(news[col], errors="coerce").dropna().mean()
                scores[asset] = 0.0 if pd.isna(mean_score) else float(mean_score)
            else:
                scores[asset] = 0.0
        return scores

    scores = {"USD": 0.0, "EUR": 0.0, "JPY": 0.0}
    keywords = {
        "USD": {
            "pos": ["fed hawkish", "higher rates", "dollar supported", "strong payrolls", "hot inflation"],
            "neg": ["fed dovish", "rate cuts", "weak payrolls", "dollar falls", "soft inflation"],
        },
        "EUR": {
            "pos": ["ecb hawkish", "euro supported", "higher eurozone inflation"],
            "neg": ["ecb dovish", "euro falls", "weak eurozone growth"],
        },
        "JPY": {
            "pos": ["boj hawkish", "yen supported", "intervention", "jpy strengthens"],
            "neg": ["boj dovish", "yen weakens", "carry trade"],
        },
    }
    text_rows = (news["headline"].fillna("") + " " + news["body"].fillna("")).str.lower()
    for text in text_rows:
        for asset, groups in keywords.items():
            scores[asset] += sum(0.2 for word in groups["pos"] if word in text)
            scores[asset] -= sum(0.2 for word in groups["neg"] if word in text)
    return {key: float(np.clip(value, -1.0, 1.0)) for key, value in scores.items()}


def _normalize_weights(config: SignalConfig) -> Dict[str, float]:
    raw = {
        "trend": max(config.trend_weight, 0.0),
        "carry": max(config.carry_weight, 0.0),
        "dollar": max(config.dollar_weight, 0.0),
        "news": max(config.news_weight, 0.0),
        "risk": max(config.risk_weight, 0.0),
    }
    total = sum(raw.values()) or 1.0
    return {key: value / total for key, value in raw.items()}


def _safe_last_return(series: pd.Series, days: int) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) <= days:
        return 0.0
    return float(clean.iloc[-1] / clean.iloc[-days - 1] - 1.0)


def _clip_score(value: float, scale: float) -> float:
    if scale == 0:
        return 0.0
    return float(np.clip(value / scale, -1.0, 1.0))


def _latest_value(market: pd.DataFrame, column: str, fallback: float = 0.0) -> float:
    if column not in market:
        return fallback
    clean = pd.to_numeric(market[column], errors="coerce").dropna()
    if clean.empty:
        return fallback
    return float(clean.iloc[-1])


def _eurusd_pullback_signal(market: pd.DataFrame) -> Dict[str, float | str]:
    series = pd.to_numeric(market["EUR/USD"], errors="coerce").dropna()
    if len(series) < 80:
        return {
            "side": "HOLD",
            "score": 0.0,
            "state": "INSUFFICIENT_HISTORY",
            "rationale": "EUR/USD pullback rule needs at least 80 observations.",
        }

    ma20 = series.rolling(20).mean()
    ma60 = series.rolling(60).mean()
    long_trend = float(ma60.iloc[-1] / ma60.iloc[-21] - 1.0) if len(ma60.dropna()) > 21 else 0.0
    short_5 = float(series.iloc[-1] / series.iloc[-6] - 1.0)
    prev_short_5 = float(series.iloc[-2] / series.iloc[-7] - 1.0)
    distance_to_ma20 = float(series.iloc[-1] / ma20.iloc[-1] - 1.0)

    uptrend = series.iloc[-1] > ma60.iloc[-1] and long_trend > 0.002
    downtrend = series.iloc[-1] < ma60.iloc[-1] and long_trend < -0.002
    pullback_ending = uptrend and distance_to_ma20 > -0.015 and short_5 > prev_short_5 and short_5 > -0.003
    rebound_ending = downtrend and distance_to_ma20 < 0.015 and short_5 < prev_short_5 and short_5 < 0.003

    if pullback_ending:
        score = min(1.0, 0.45 + abs(long_trend) * 20 + max(short_5, 0.0) * 10)
        return {
            "side": "LONG",
            "score": score,
            "state": "PULLBACK_LONG",
            "rationale": "长期上升趋势成立，短期回调动能改善，按回调结束买入 EUR/USD。",
        }
    if rebound_ending:
        score = -min(1.0, 0.45 + abs(long_trend) * 20 + abs(min(short_5, 0.0)) * 10)
        return {
            "side": "SHORT",
            "score": score,
            "state": "REBOUND_SHORT",
            "rationale": "长期下降趋势成立，短期反弹动能转弱，按反弹结束做空 EUR/USD。",
        }

    return {
        "side": "HOLD",
        "score": 0.0,
        "state": "WAIT_FOR_PULLBACK_SETUP",
        "rationale": "未同时满足长期趋势过滤与短期回调/反弹结束条件。",
    }


def generate_trade_signals(
    market: pd.DataFrame,
    news: pd.DataFrame,
    config: Optional[SignalConfig] = None,
) -> pd.DataFrame:
    config = config or SignalConfig()
    weights = _normalize_weights(config)
    news_scores = score_news(news)
    as_of = market.index.max().date().isoformat()
    dxy_column = "DXY" if "DXY" in market.columns else "DXY_PROXY"
    dxy_20d = _safe_last_return(market[dxy_column], 20)
    vix = _latest_value(market, "vix", 18.0)

    rows = []
    for instrument in WATCHLIST:
        price_col = dxy_column if instrument == "DXY_PROXY" else instrument
        close = _latest_value(market, price_col)
        trend_20 = _safe_last_return(market[price_col], 20)
        trend_60 = _safe_last_return(market[price_col], 60)
        trend_score = _clip_score(0.65 * trend_20 + 0.35 * trend_60, 0.03)

        if instrument == "EUR/USD":
            carry = (_latest_value(market, "ecb_rate", 3.75) - _latest_value(market, "fed_rate", 5.25)) / 3.0
            yield_carry = (_latest_value(market, "de10y", 2.5) - _latest_value(market, "us10y", 4.25)) / 3.0
            carry_policy_score = float(np.clip(0.7 * carry + 0.3 * yield_carry, -1.0, 1.0))
            dxy_cycle_score = -_clip_score(dxy_20d, 0.025)
            news_policy_score = float(np.clip(news_scores["EUR"] - news_scores["USD"], -1.0, 1.0))
            risk_sentiment_score = -_clip_score(vix - 18.0, 12.0)
        elif instrument == "USD/JPY":
            carry = (_latest_value(market, "fed_rate", 5.25) - _latest_value(market, "boj_rate", 0.25)) / 5.0
            yield_carry = (_latest_value(market, "us10y", 4.25) - _latest_value(market, "jp10y", 1.0)) / 4.0
            carry_policy_score = float(np.clip(0.7 * carry + 0.3 * yield_carry, -1.0, 1.0))
            dxy_cycle_score = _clip_score(dxy_20d, 0.025)
            news_policy_score = float(np.clip(news_scores["USD"] - news_scores["JPY"], -1.0, 1.0))
            risk_sentiment_score = -_clip_score(vix - 20.0, 12.0)
        else:
            carry_policy_score = float(np.clip((_latest_value(market, "fed_rate", 5.25) - 3.0) / 3.0, -1.0, 1.0))
            dxy_cycle_score = _clip_score(dxy_20d, 0.025)
            news_policy_score = float(np.clip(news_scores["USD"] - 0.5 * news_scores["EUR"] - 0.5 * news_scores["JPY"], -1.0, 1.0))
            risk_sentiment_score = _clip_score(vix - 18.0, 12.0)

        composite = (
            weights["trend"] * trend_score
            + weights["carry"] * carry_policy_score
            + weights["dollar"] * dxy_cycle_score
            + weights["news"] * news_policy_score
            + weights["risk"] * risk_sentiment_score
        )
        if composite >= config.score_threshold:
            side = "LONG"
        elif composite <= -config.score_threshold:
            side = "SHORT"
        else:
            side = "HOLD"
        rule_note = ""
        if config.rule_strategy == "eurusd_trend_pullback" and instrument == "EUR/USD":
            rule = _eurusd_pullback_signal(market)
            side = str(rule["side"])
            composite = float(rule["score"])
            rule_note = str(rule["rationale"])
        confidence = abs(composite)
        target_weight = 0.0 if side == "HOLD" else float(np.clip(composite, -1.0, 1.0))
        signal_state = "TRADE" if side != "HOLD" else ("WATCH" if confidence >= config.score_threshold * 0.75 else "NO_ACTION")
        if rule_note and side == "HOLD":
            signal_state = "WAIT"
        rationale = "趋势 {:.2f}，利差/政策 {:.2f}，美元周期 {:.2f}，新闻 {:.2f}，风险 {:.2f}".format(
            trend_score,
            carry_policy_score,
            dxy_cycle_score,
            news_policy_score,
            risk_sentiment_score,
        )
        if rule_note:
            rationale = "{}；规则策略：{}".format(rationale, rule_note)
        rows.append(
            {
                "as_of": as_of,
                "instrument": instrument,
                "close": close,
                "side": side,
                "target_weight": target_weight,
                "confidence": confidence,
                "composite_score": composite,
                "trend_score": trend_score,
                "carry_policy_score": carry_policy_score,
                "dxy_cycle_score": dxy_cycle_score,
                "news_policy_score": news_policy_score,
                "risk_sentiment_score": risk_sentiment_score,
                "signal_state": signal_state,
                "rationale": rationale,
                "rule_strategy": config.rule_strategy,
                "demo_notional_usd": config.demo_notional_usd,
            }
        )
    return pd.DataFrame(rows)


def _generate_signal_history(market: pd.DataFrame, news: pd.DataFrame, config: SignalConfig) -> pd.DataFrame:
    rows = []
    for idx in range(max(2, min(60, len(market) - 1)), len(market)):
        subset = market.iloc[: idx + 1]
        signals = generate_trade_signals(subset, _news_as_of(news, subset.index.max()), config)
        rows.append(signals)
    if not rows:
        return generate_trade_signals(market, _news_as_of(news, market.index.max()), config)
    return pd.concat(rows, ignore_index=True)


def _news_as_of(news: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    if news is None or news.empty or "timestamp" not in news.columns:
        return news
    cutoff = pd.Timestamp(as_of).normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    timestamps = pd.to_datetime(news["timestamp"], errors="coerce").dt.tz_localize(None)
    return news.loc[timestamps <= cutoff].copy()


def _shadow_backtest(market: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["date", "signal_date", "daily_return", "equity", "drawdown"])
    prices = market[["EUR/USD", "USD/JPY"]].copy()
    dxy_col = "DXY" if "DXY" in market.columns else "DXY_PROXY"
    prices["DXY_PROXY"] = market[dxy_col]
    returns = prices.pct_change().fillna(0.0)
    rows = []
    equity = 1.0
    peak = 1.0
    for date, day_rows in history.groupby("as_of"):
        signal_day = pd.to_datetime(date)
        if signal_day not in returns.index:
            continue
        signal_pos = returns.index.get_loc(signal_day)
        if isinstance(signal_pos, slice) or isinstance(signal_pos, np.ndarray):
            continue
        return_pos = int(signal_pos) + 1
        if return_pos >= len(returns.index):
            continue
        return_day = returns.index[return_pos]
        daily = 0.0
        for _, row in day_rows.iterrows():
            instrument = row["instrument"]
            weight = float(row.get("target_weight") or 0.0)
            daily += weight * float(returns.loc[return_day, instrument])
        daily = float(np.clip(daily, -0.05, 0.05))
        equity *= 1.0 + daily
        peak = max(peak, equity)
        rows.append(
            {
                "date": return_day.date().isoformat(),
                "signal_date": signal_day.date().isoformat(),
                "daily_return": daily,
                "equity": equity,
                "drawdown": equity / peak - 1.0,
            }
        )
    return pd.DataFrame(rows)


def _backtest_summary(backtest: pd.DataFrame) -> pd.DataFrame:
    if backtest.empty:
        return pd.DataFrame([{"total_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "active_days": 0}])
    returns = pd.to_numeric(backtest["daily_return"], errors="coerce").fillna(0.0)
    sharpe = 0.0 if returns.std() == 0 else float(returns.mean() / returns.std() * np.sqrt(252))
    return pd.DataFrame(
        [
            {
                "total_return": float(backtest["equity"].iloc[-1] - 1.0),
                "max_drawdown": float(backtest["drawdown"].min()),
                "sharpe": sharpe,
                "active_days": int((returns.abs() > 0).sum()),
            }
        ]
    )


def prepare_news_output(news: pd.DataFrame) -> pd.DataFrame:
    if news is None or news.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "timestamp",
                "topic",
                "headline",
                "body",
                "usd_score",
                "eur_score",
                "jpy_score",
                "news_confidence",
                "news_event_type",
                "news_score_reason",
            ]
        )
    output = news.copy()
    output["timestamp"] = pd.to_datetime(output["timestamp"]).dt.tz_localize(None)
    output["date"] = output["timestamp"].dt.date.astype(str)
    for col in ("usd_score", "eur_score", "jpy_score"):
        if col not in output.columns:
            output[col] = 0.0
    for col in ("news_confidence", "news_event_type", "news_score_reason"):
        if col not in output.columns:
            output[col] = 0.0 if col == "news_confidence" else ""
    return output[
        [
            "date",
            "timestamp",
            "topic",
            "headline",
            "body",
            "usd_score",
            "eur_score",
            "jpy_score",
            "news_confidence",
            "news_event_type",
            "news_score_reason",
        ]
    ]


def build_business_report(signals: pd.DataFrame, summary: pd.DataFrame, news: pd.DataFrame, market_source: str, news_source: str) -> str:
    lines = [
        "# 外汇宏观新闻信号报告",
        "",
        "## 数据来源",
        "- 行情：{}".format(market_source),
        "- 新闻：{}".format(news_source),
        "",
        "## 最新信号",
    ]
    for _, row in signals.iterrows():
        lines.append(
            "- {instrument}：{side}，分数 {score:.3f}，置信度 {confidence:.3f}。{reason}".format(
                instrument=row["instrument"],
                side=row["side"],
                score=float(row["composite_score"]),
                confidence=float(row["confidence"]),
                reason=row["rationale"],
            )
        )
    if not summary.empty:
        s = summary.iloc[0]
        lines.extend(
            [
                "",
                "## 影子回测",
                "- 总收益：{:.2%}".format(float(s["total_return"])),
                "- 最大回撤：{:.2%}".format(float(s["max_drawdown"])),
                "- Sharpe：{:.2f}".format(float(s["sharpe"])),
                "- 有持仓天数：{}".format(int(s["active_days"])),
                "- 口径：T 日收盘后生成信号，使用 T+1 日收益计算，避免同日收益前视。",
            ]
        )
    lines.extend(["", "## 新闻覆盖", "- 本次新闻条数：{}".format(len(news))])
    if not news.empty and {"usd_score", "eur_score", "jpy_score"}.issubset(news.columns):
        lines.append(
            "- 新闻平均分：USD {:.2f}，EUR {:.2f}，JPY {:.2f}".format(
                float(pd.to_numeric(news["usd_score"], errors="coerce").fillna(0.0).mean()),
                float(pd.to_numeric(news["eur_score"], errors="coerce").fillna(0.0).mean()),
                float(pd.to_numeric(news["jpy_score"], errors="coerce").fillna(0.0).mean()),
            )
        )
    lines.extend(["", "## 说明", "- 本报告只生成研究信号，不自动下单。", "- 历史信号只使用信号日期之前可见的新闻。"])
    return "\n".join(lines) + "\n"


def run_demo(
    market_data_path: Optional[str | Path] = None,
    news_path: Optional[str | Path] = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    use_lseg: bool = False,
    lseg_start: str = "2025-01-01",
    lseg_end: Optional[str] = None,
    lseg_ric_map: Optional[str | Path] = None,
    lseg_policy_rates: Optional[str | Path] = None,
    lseg_news_query: str = "Reuters AND (EUR/USD OR USD/JPY OR DXY OR Fed OR ECB OR BOJ OR inflation OR payrolls)",
    lseg_news_count: int = 100,
    config: Optional[SignalConfig] = None,
) -> Dict[str, pd.DataFrame | str]:
    config = config or SignalConfig()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if use_lseg:
        market = fetch_lseg_market_data(
            start=lseg_start,
            end=lseg_end or pd.Timestamp.today().date().isoformat(),
            ric_map=load_ric_map(lseg_ric_map),
            policy_rates=load_policy_rates(lseg_policy_rates),
        )
        market_source = "LSEG/Refinitiv 行情"
        if news_path:
            news = load_reuters_export(news_path)
            news_source = "Reuters 新闻 CSV"
        else:
            news = fetch_lseg_reuters_news(lseg_news_query, count=lseg_news_count)
            news_source = "LSEG/Reuters 新闻"
    else:
        market = load_market_data(market_data_path)
        news = load_reuters_export(news_path)
        market_source = "CSV 行情"
        news_source = "Reuters 新闻 CSV"

    if config.news_score_mode == "llm":
        news = score_news_with_llm(news)
        news_source = "{} + 大模型评分".format(news_source)

    signals = generate_trade_signals(market, news, config)
    history = _generate_signal_history(market, news, config)
    backtest = _shadow_backtest(market, history)
    summary = _backtest_summary(backtest)
    news_output = prepare_news_output(news)
    report = build_business_report(signals, summary, news_output, market_source=market_source, news_source=news_source)

    signals.to_csv(output_path / "fx_macro_news_demo_signals.csv", index=False)
    history.to_csv(output_path / "fx_macro_news_demo_signal_history.csv", index=False)
    backtest.to_csv(output_path / "fx_macro_news_demo_shadow_backtest.csv", index=False)
    summary.to_csv(output_path / "fx_macro_news_demo_backtest_summary.csv", index=False)
    news_output.to_csv(output_path / "fx_macro_news_demo_news.csv", index=False)
    (output_path / "fx_macro_news_demo_report.md").write_text(report, encoding="utf-8")

    return {
        "signals": signals,
        "history": history,
        "backtest": backtest,
        "summary": summary,
        "news": news_output,
        "report": report,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FX macro-news signal demo")
    parser.add_argument("--market-data")
    parser.add_argument("--reuters-news")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--use-lseg", action="store_true")
    parser.add_argument("--lseg-start", default="2025-01-01")
    parser.add_argument("--lseg-end")
    parser.add_argument("--lseg-ric-map")
    parser.add_argument("--lseg-policy-rates")
    parser.add_argument("--lseg-news-query", default="Reuters AND (EUR/USD OR USD/JPY OR DXY OR Fed OR ECB OR BOJ OR inflation OR payrolls)")
    parser.add_argument("--lseg-news-count", type=int, default=100)
    parser.add_argument("--trend-weight", type=float, default=30.0)
    parser.add_argument("--carry-weight", type=float, default=25.0)
    parser.add_argument("--dollar-weight", type=float, default=20.0)
    parser.add_argument("--news-weight", type=float, default=15.0)
    parser.add_argument("--risk-weight", type=float, default=10.0)
    parser.add_argument("--score-threshold", type=float, default=0.35)
    parser.add_argument("--rule-strategy", default="factor_blend")
    parser.add_argument("--news-score-mode", choices=["rule", "llm"], default="rule")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = SignalConfig(
        trend_weight=args.trend_weight,
        carry_weight=args.carry_weight,
        dollar_weight=args.dollar_weight,
        news_weight=args.news_weight,
        risk_weight=args.risk_weight,
        score_threshold=args.score_threshold,
        rule_strategy=args.rule_strategy,
        news_score_mode=args.news_score_mode,
    )
    result = run_demo(
        market_data_path=args.market_data,
        news_path=args.reuters_news,
        output_dir=args.output_dir,
        use_lseg=args.use_lseg,
        lseg_start=args.lseg_start,
        lseg_end=args.lseg_end,
        lseg_ric_map=args.lseg_ric_map,
        lseg_policy_rates=args.lseg_policy_rates,
        lseg_news_query=args.lseg_news_query,
        lseg_news_count=args.lseg_news_count,
        config=config,
    )
    print(result["report"])


if __name__ == "__main__":
    main()
