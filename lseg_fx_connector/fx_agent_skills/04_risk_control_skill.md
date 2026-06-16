---
name: fx-agent-risk-review
description: FX Agent risk-review workflow for data quality, signal completeness, news coverage, target-weight limits, shadow backtest sanity, and human-approval boundaries.
category: risk-control
---

# FX Agent Risk Review

Use this skill after signal generation and before presenting a trading candidate to the user.

## Review Objective

The Agent must decide whether the run is ready for desk review, only suitable for observation, or blocked by data-quality issues. It must not convert a research signal into an executable order.

## Required Checks

- Data connection: LSEG/Refinitiv session opened and returned usable data.
- Signal completeness: latest signals exist for `EUR/USD`, `USD/JPY`, and `DXY_PROXY`.
- News coverage: Reuters/LSEG news exists or the lack of news is explicitly flagged.
- Weight constraint: target weights stay within bounded research limits.
- Backtest sanity: shadow backtest summary is present and max drawdown is not excessive.
- Source integrity: no offline samples, synthetic prices, or old output files are passed as current data.

## Decision Labels

- `交易候选`: score crossed the threshold and all required checks are acceptable.
- `重点观察`: signal is close to threshold or a nonblocking caveat exists.
- `暂不交易`: signal is weak or incomplete.
- `数据阻断`: required market data, news shape, or signal output is missing.

## Failure Handling

- If the signal engine returns success but writes zero signal rows, mark the run as failed.
- If LSEG returns empty required columns, explain the missing RIC or entitlement.
- If direct DXY is unavailable but proxy components exist, continue with `DXY_PROXY` and disclose it.
- If Reuters News is unavailable, continue only when the strategy can tolerate zero news coverage; otherwise mark as insufficient evidence.

## Output Contract

The risk review must emit structured checks with:

- `name`
- `status`
- `message`

Statuses should be one of:

- `通过`
- `关注`
- `未通过`

## Communication Style

Lead with the blocking issue when blocked. Otherwise summarize the trade candidates first, then caveats. Keep the language suitable for a finance business user who may not be technical.
