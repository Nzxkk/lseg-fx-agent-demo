---
name: fx-macro-signal-decision
description: Multi-factor FX signal construction and decision workflow. Combines trend, carry/policy, dollar cycle, news, and risk sentiment into transparent LONG/SHORT/HOLD research signals.
category: signal-research
---

# FX Macro Signal Decision

Use this skill when the Agent needs to convert validated market data and normalized news into transparent FX research signals.

## Instruments

- `EUR/USD`: positive score means long EUR and short USD.
- `USD/JPY`: positive score means long USD and short JPY.
- `DXY_PROXY`: positive score means long broad USD exposure.

## Factor Stack

- Trend: 20-day and 60-day price momentum.
- Carry/policy: policy-rate and 10Y-yield differentials.
- Dollar cycle: DXY or DXY proxy trend confirmation.
- News/policy: USD/EUR/JPY event scores from Reuters/LSEG news or scored CSV.
- Risk sentiment: VIX-style risk proxy and risk-off behavior.

## Decision Rules

1. Normalize user-provided factor weights.
2. Compute each factor score on a bounded -1 to +1 scale.
3. Combine factors into `composite_score`.
4. If `composite_score >= score_threshold`, assign `LONG`.
5. If `composite_score <= -score_threshold`, assign `SHORT`.
6. Otherwise assign `HOLD`.
7. If the score is near but below threshold, classify it as `WATCH` instead of a trade candidate.

## Manual Weighting Rules

- User-adjusted weights should change factor influence, not raw data.
- Zero-weight factors are allowed.
- If all weights are zero, fall back to equal normalization through a nonzero denominator.
- Never alter price or news inputs to force a signal.

## Output Contract

Each latest signal row must include:

- `as_of`
- `instrument`
- `close`
- `side`
- `target_weight`
- `confidence`
- `composite_score`
- `trend_score`
- `carry_policy_score`
- `dxy_cycle_score`
- `news_policy_score`
- `risk_sentiment_score`
- `signal_state`
- `rationale`

## Research Boundary

This skill creates research signals only. It must not submit orders, suggest automatic execution, or hide uncertainty. Human review is required before any business use.
