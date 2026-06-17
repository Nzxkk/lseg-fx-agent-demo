"""Render a local HTML dashboard for the LSEG FX demo outputs."""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd


CONNECTOR_DIR = Path(__file__).resolve().parent
ROOT = CONNECTOR_DIR.parent
OUTPUT_DIR = CONNECTOR_DIR / "output"
DASHBOARD_PATH = CONNECTOR_DIR / "dashboard.html"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _fmt_pct(value: float) -> str:
    return f"{value:+.2%}"


def _fmt_num(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _sparkline(points: list[float], width: int = 760, height: int = 180) -> str:
    if not points:
        return "<div class='empty'>暂无回测曲线</div>"
    min_v = min(points)
    max_v = max(points)
    span = max(max_v - min_v, 1e-9)
    step = width / max(len(points) - 1, 1)
    coords = []
    for idx, value in enumerate(points):
        x = idx * step
        y = height - ((value - min_v) / span * (height - 16) + 8)
        coords.append(f"{x:.2f},{y:.2f}")
    polyline = " ".join(coords)
    return f"""
    <svg class="equity-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Equity curve">
      <line x1="0" y1="{height - 8}" x2="{width}" y2="{height - 8}" class="axis" />
      <polyline points="{polyline}" class="equity-line" fill="none" />
    </svg>
    """


def _signal_cards(signals: pd.DataFrame) -> str:
    if signals.empty:
        return "<div class='empty'>暂无最新信号</div>"
    cards = []
    for _, row in signals.iterrows():
        side = str(row.get("side", "HOLD"))
        cls = side.lower()
        cards.append(
            f"""
            <article class="signal-card {cls}">
              <div class="signal-top">
                <span class="instrument">{escape(str(row.get("instrument", "")))}</span>
                <span class="side">{escape(side)}</span>
              </div>
              <div class="price">{_fmt_num(float(row.get("close", 0.0)), 4)}</div>
              <div class="signal-grid">
                <div><span>权重</span><strong>{float(row.get("target_weight", 0.0)):+.2f}</strong></div>
                <div><span>置信度</span><strong>{float(row.get("confidence", 0.0)):.2f}</strong></div>
                <div><span>分数</span><strong>{float(row.get("composite_score", 0.0)):+.2f}</strong></div>
              </div>
              <p>{escape(str(row.get("rationale", "")))}</p>
            </article>
            """
        )
    return "\n".join(cards)


def _factor_table(signals: pd.DataFrame) -> str:
    if signals.empty:
        return "<div class='empty'>暂无因子明细</div>"
    rows = []
    for _, row in signals.iterrows():
        rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('instrument', '')))}</td>"
            f"<td>{float(row.get('trend_score', 0.0)):+.2f}</td>"
            f"<td>{float(row.get('carry_policy_score', 0.0)):+.2f}</td>"
            f"<td>{float(row.get('dxy_cycle_score', 0.0)):+.2f}</td>"
            f"<td>{float(row.get('news_policy_score', 0.0)):+.2f}</td>"
            f"<td>{float(row.get('risk_sentiment_score', 0.0)):+.2f}</td>"
            "</tr>"
        )
    return f"""
    <table>
      <thead>
        <tr>
          <th>标的</th>
          <th>趋势</th>
          <th>利差/政策</th>
          <th>美元周期</th>
          <th>新闻事件</th>
          <th>风险情绪</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def render_dashboard() -> Path:
    signals = _read_csv(OUTPUT_DIR / "fx_macro_news_demo_signals.csv")
    summary = _read_csv(OUTPUT_DIR / "fx_macro_news_demo_backtest_summary.csv")
    backtest = _read_csv(OUTPUT_DIR / "fx_macro_news_demo_shadow_backtest.csv")

    as_of = signals["as_of"].iloc[0] if not signals.empty and "as_of" in signals else "N/A"
    summary_row = summary.iloc[0].to_dict() if not summary.empty else {}
    equity_points = backtest["equity"].dropna().astype(float).tolist() if "equity" in backtest else []

    total_return = float(summary_row.get("total_return", 0.0))
    max_drawdown = float(summary_row.get("max_drawdown", 0.0))
    sharpe = float(summary_row.get("sharpe", 0.0))
    active_days = int(summary_row.get("active_days", 0))

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LSEG FX Signal Dashboard</title>
  <style>
    :root {{
      --bg: #f6f5f1;
      --panel: #ffffff;
      --ink: #202124;
      --muted: #6b6f76;
      --line: #dedbd2;
      --green: #16794c;
      --red: #b23a32;
      --amber: #9a6a06;
      --blue: #2f65b0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }}
    .page {{ max-width: 1180px; margin: 0 auto; padding: 28px 24px 48px; }}
    header {{ display: flex; justify-content: space-between; gap: 24px; align-items: flex-end; border-bottom: 1px solid var(--line); padding-bottom: 18px; }}
    h1 {{ margin: 0; font-size: 28px; line-height: 1.2; font-weight: 720; }}
    .subtitle {{ margin: 8px 0 0; color: var(--muted); font-size: 14px; }}
    .asof {{ color: var(--muted); font-size: 14px; text-align: right; white-space: nowrap; }}
    section {{ margin-top: 24px; }}
    h2 {{ font-size: 17px; margin: 0 0 12px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric, .signal-card, .chart-panel, .table-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(30, 30, 30, 0.04);
    }}
    .metric {{ padding: 14px 16px; min-height: 88px; }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 8px; font-size: 24px; }}
    .signals {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }}
    .signal-card {{ padding: 16px; min-height: 218px; border-top-width: 4px; }}
    .signal-card.long {{ border-top-color: var(--green); }}
    .signal-card.short {{ border-top-color: var(--red); }}
    .signal-card.hold {{ border-top-color: var(--amber); }}
    .signal-top {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; }}
    .instrument {{ font-weight: 720; font-size: 18px; }}
    .side {{ font-size: 13px; font-weight: 720; padding: 4px 9px; border: 1px solid var(--line); border-radius: 999px; }}
    .price {{ margin-top: 14px; font-size: 26px; font-weight: 720; }}
    .signal-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 14px; }}
    .signal-grid div {{ border-top: 1px solid var(--line); padding-top: 8px; }}
    .signal-grid span {{ display: block; color: var(--muted); font-size: 12px; }}
    .signal-grid strong {{ display: block; margin-top: 3px; font-size: 16px; }}
    .signal-card p {{ color: var(--muted); font-size: 13px; line-height: 1.45; min-height: 40px; }}
    .chart-panel {{ padding: 16px; }}
    .equity-chart {{ width: 100%; height: 220px; display: block; }}
    .axis {{ stroke: var(--line); stroke-width: 1; }}
    .equity-line {{ stroke: var(--blue); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }}
    .table-panel {{ overflow: hidden; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: var(--muted); font-weight: 650; background: #fbfaf7; }}
    .empty {{ padding: 24px; color: var(--muted); background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    @media (max-width: 860px) {{
      header {{ display: block; }}
      .asof {{ text-align: left; margin-top: 12px; }}
      .metrics, .signals {{ grid-template-columns: 1fr; }}
      .page {{ padding: 20px 14px 36px; }}
      h1 {{ font-size: 24px; }}
      table {{ min-width: 720px; }}
      .table-panel {{ overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div>
        <h1>LSEG 外汇宏观新闻信号台</h1>
        <p class="subtitle">EUR/USD、USD/JPY、DXY 的交易信号、因子拆解和影子回测</p>
      </div>
      <div class="asof">信号日期：{escape(str(as_of))}</div>
    </header>

    <section>
      <h2>影子回测摘要</h2>
      <div class="metrics">
        <div class="metric"><span>总收益</span><strong>{_fmt_pct(total_return)}</strong></div>
        <div class="metric"><span>最大回撤</span><strong>{_fmt_pct(max_drawdown)}</strong></div>
        <div class="metric"><span>Sharpe</span><strong>{_fmt_num(sharpe, 2)}</strong></div>
        <div class="metric"><span>有持仓天数</span><strong>{active_days}</strong></div>
      </div>
    </section>

    <section>
      <h2>最新交易信号</h2>
      <div class="signals">{_signal_cards(signals)}</div>
    </section>

    <section>
      <h2>净值曲线</h2>
      <div class="chart-panel">{_sparkline(equity_points)}</div>
    </section>

    <section>
      <h2>因子明细</h2>
      <div class="table-panel">{_factor_table(signals)}</div>
    </section>
  </main>
</body>
</html>
"""
    DASHBOARD_PATH.write_text(html, encoding="utf-8")
    return DASHBOARD_PATH


if __name__ == "__main__":
    path = render_dashboard()
    print(path)
