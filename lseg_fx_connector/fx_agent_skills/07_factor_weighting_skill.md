---
name: fx-factor-weighting
description: Manual factor-weight tuning workflow for trend, carry/policy, dollar cycle, news, risk sentiment, and signal threshold controls.
category: user-control
---

# FX Factor Weighting

Use this skill when the user manually changes signal proportions on the dashboard.

## Controlled Inputs

- Trend weight
- Carry/policy weight
- Dollar-cycle weight
- News weight
- Risk-sentiment weight
- Signal threshold

## Rules

- Manual weights change factor contribution only.
- Manual weights must not modify market prices, news rows, or backtest observations.
- Normalize weights before combining factors.
- Keep the threshold separate from factor weights.
- If the user sets a factor to zero, exclude that factor from the composite score.

## Interpretation Guide

- Higher trend weight: the model follows recent price momentum more aggressively.
- Higher carry/policy weight: rate differentials and central-bank stance matter more.
- Higher dollar-cycle weight: DXY/DXY_PROXY confirmation matters more.
- Higher news weight: recent macro headlines affect direction more.
- Higher risk weight: risk-off/risk-on context matters more.
- Higher threshold: fewer trades, more HOLD.

## Output Contract

The Agent should preserve the user-selected weights in `params`, show them in the report, and make clear that weight changes are scenario analysis rather than model retraining.
