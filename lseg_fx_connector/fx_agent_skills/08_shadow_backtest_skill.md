---
name: fx-shadow-backtest
description: Shadow backtest workflow for sanity-checking FX research signals without live execution. Produces equity, drawdown, active-day count, and Sharpe-like summary metrics.
category: validation
---

# FX Shadow Backtest

Use this skill after signal history is generated and before results are presented to business users.

## Purpose

The shadow backtest is a sanity check. It is not a production performance claim and does not imply the strategy is tradable.

## Inputs

- Historical point-in-time signal rows.
- Market returns for `EUR/USD`, `USD/JPY`, and `DXY_PROXY`.
- Target weights produced by the signal engine.

## Rules

- Use point-in-time signals only.
- Do not use future news or future prices.
- Report total return, maximum drawdown, active days, and a Sharpe-like metric.
- If there are too few observations, report insufficient evidence instead of overstating performance.

## Output Contract

The Agent should create:

- `fx_macro_news_demo_signal_history.csv`
- `fx_macro_news_demo_shadow_backtest.csv`
- `fx_macro_news_demo_backtest_summary.csv`

The page should display the summary and equity curve as research diagnostics only.
