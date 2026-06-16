---
name: dxy-proxy-construction
description: ICE-style DXY proxy construction workflow for accounts where direct DXY RICs are unavailable. Uses six FX components and clearly labels proxy output.
category: market-transform
---

# DXY Proxy Construction

Use this skill when direct DXY RICs return empty data but the business still needs a broad USD-cycle factor.

## Formula

Use the ICE-style component approximation:

```text
DXY_PROXY =
50.14348112
* EURUSD^-0.576
* USDJPY^0.136
* GBPUSD^-0.119
* USDCAD^0.091
* USDSEK^0.042
* USDCHF^0.036
```

## Required Components

- `EUR/USD` from `EUR=`
- `USD/JPY` from `JPY=`
- `GBP/USD` from `GBP=`
- `USD/CAD` from `CAD=`
- `USD/SEK` from `SEK=`
- `USD/CHF` from `CHF=`

## Rules

- Use the proxy only when direct DXY is unavailable or unusable.
- Label the displayed instrument as `DXY_PROXY`.
- Do not present proxy values as official DXY prints.
- If any required component is missing, block the DXY factor and explain the missing component.

## Output Contract

The Agent must disclose:

- whether direct DXY or proxy was used,
- which components were required,
- whether any component was missing,
- that `DXY_PROXY` is a research proxy, not an official index quote.
