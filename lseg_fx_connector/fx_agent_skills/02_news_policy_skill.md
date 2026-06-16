---
name: reuters-fx-news-policy
description: Reuters/LSEG FX macro-news workflow for central-bank, inflation, labor-market, and risk-event interpretation. Separates API-provided news text from locally derived USD/EUR/JPY policy scores.
category: news-intelligence
---

# Reuters FX News Policy

Use this skill when the FX Agent needs to incorporate Reuters/LSEG news, central-bank events, macro-policy language, or event-risk context into FX research signals.

## Scope

- Currencies: USD, EUR, JPY.
- Instruments affected: `EUR/USD`, `USD/JPY`, `DXY_PROXY`.
- Policy institutions: Fed, ECB, BOJ.
- Macro topics: inflation, payrolls, growth, risk sentiment, intervention, rate guidance.

## Source Boundary

- Reuters/LSEG provides news metadata, timestamps, headlines, and story text.
- Reuters/LSEG does not provide the final trade signal used by this demo.
- `usd_score`, `eur_score`, and `jpy_score` are local event scores unless the imported CSV explicitly includes those numeric columns.
- The Agent must tell users when news scores are locally inferred.

## Tool Flow

1. Query LSEG/Reuters news with the FX macro query.
2. Normalize the response into `timestamp`, `headline`, `body`, and `topic`.
3. Preserve the original headline and story text in output files.
4. Score USD/EUR/JPY only after the source text is normalized.
5. If a Reuters export CSV already has score columns, honor those columns instead of recomputing from keywords.
6. Save daily news rows to `fx_macro_news_demo_news.csv`.

## Scoring Guidance

- Hawkish Fed, strong U.S. labor, sticky inflation: USD positive.
- Dovish Fed, weak U.S. labor, softer inflation: USD negative.
- Hawkish ECB or stronger euro-area inflation: EUR positive.
- Dovish ECB or weak euro-area growth: EUR negative.
- BOJ normalization, intervention risk, yen strengthening language: JPY positive.
- Carry-trade extension or yen-weakening language: JPY negative.

## Failure Conditions

- News API is unavailable because the account lacks Reuters News entitlement.
- The LSEG library version does not expose a supported news headline API.
- The response lacks a usable headline field.

## Output Contract

The news output must include:

- `date`
- `timestamp`
- `topic`
- `headline`
- `body`
- `usd_score`
- `eur_score`
- `jpy_score`

If no news is available, return an empty but correctly shaped dataframe and mark news coverage as a risk caveat.
