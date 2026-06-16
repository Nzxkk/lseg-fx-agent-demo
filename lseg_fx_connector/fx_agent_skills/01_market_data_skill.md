---
name: lseg-fx-market-data
description: LSEG/Refinitiv FX and rates market-data workflow for EUR/USD, USD/JPY, and DXY_PROXY. Validates entitlements, RIC coverage, price fields, DXY fallback construction, and no-synthetic-data boundaries.
category: data-source
---

# LSEG FX Market Data

Use this skill when the FX Agent needs to collect or validate market data for EUR/USD, USD/JPY, DXY, dollar-cycle signals, policy-rate inputs, or cross-market risk context.

## Scope

- Primary instruments: `EUR/USD`, `USD/JPY`, `DXY_PROXY`.
- Required FX RICs: `EUR=`, `JPY=`.
- DXY direct RIC may be unavailable. When direct DXY is empty, construct `DXY_PROXY` from `EUR=`, `JPY=`, `GBP=`, `CAD=`, `SEK=`, and `CHF=`.
- Macro/risk inputs may come from LSEG if entitled; otherwise use explicit local configuration from `policy_rates.json`.

## Data Rules

- Never use offline sample data, generated prices, or stale CSV files as if they were live market data.
- Prefer BID/ASK midpoint when both fields are available.
- Use `TRDPRC_1`, close, or last-price fields only when BID/ASK is not usable.
- Treat all-empty fields, entitlement errors, and missing RICs as data-quality failures.
- If a yield RIC returns bond prices around 98-100 instead of percentage yields, reject it for carry scoring and use the configured fallback rate.

## Tool Flow

1. Open a local LSEG/Refinitiv data session.
2. Request daily history for the configured RIC map.
3. Normalize LSEG dataframe shapes into canonical columns.
4. Build `DXY_PROXY` when direct DXY is unavailable.
5. Forward-fill market data only after validating that at least one real observation exists.
6. Write outputs only after required columns are present.

## Failure Conditions

- No usable `EUR/USD` or `USD/JPY` data.
- Direct DXY unavailable and at least one DXY proxy component is missing.
- LSEG Workspace/Eikon session is not opened.
- Data library package is missing.
- Output file has zero signal rows after a supposedly successful run.

## Output Contract

The skill must produce a market dataframe with:

- `EUR/USD`
- `USD/JPY`
- `DXY`
- `vix`
- `fed_rate`
- `ecb_rate`
- `boj_rate`
- `us10y`
- `de10y`
- `jp10y`

If this contract is not met, the Agent should stop and explain which input is missing.
