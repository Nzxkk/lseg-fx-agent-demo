"""Standalone CodeBook script: generate FX signals with Refinitiv Workspace data.

Paste this file into a persistent CodeBook folder outside __Examples__ and run it.
"""

import numpy as np
import pandas as pd
import refinitiv.data as rd
from IPython.display import HTML, display


POLICY = {
    "fed_rate": 5.25,
    "ecb_rate": 3.75,
    "boj_rate": 0.25,
    "us10y": 4.25,
    "de10y": 2.50,
    "jp10y": 1.00,
    "vix": 18.0,
}

ENTRY_THRESHOLD = 0.35
WATCH_THRESHOLD = 0.25

RICS = {
    "EUR/USD": "EUR=",
    "USD/JPY": "JPY=",
    "GBP/USD": "GBP=",
    "USD/CAD": "CAD=",
    "USD/SEK": "SEK=",
    "USD/CHF": "CHF=",
}


def as_score(value, scale):
    if pd.isna(value) or scale == 0:
        return 0.0
    return float(np.clip(value / scale, -1.0, 1.0))


def side(score, threshold=ENTRY_THRESHOLD):
    if score >= threshold:
        return "LONG"
    if score <= -threshold:
        return "SHORT"
    return "HOLD"


def watch_direction(score, threshold=WATCH_THRESHOLD):
    if score >= ENTRY_THRESHOLD:
        return "TRADE_LONG"
    if score <= -ENTRY_THRESHOLD:
        return "TRADE_SHORT"
    if score >= threshold:
        return "WATCH_LONG"
    if score <= -threshold:
        return "WATCH_SHORT"
    return "NO_EDGE"


def mid_from_row(row):
    bid = pd.to_numeric(row.get("BID"), errors="coerce")
    ask = pd.to_numeric(row.get("ASK"), errors="coerce")
    last = pd.to_numeric(row.get("CF_LAST"), errors="coerce")
    if pd.notna(bid) and pd.notna(ask):
        return float((bid + ask) / 2.0)
    if pd.notna(last):
        return float(last)
    return np.nan


def dxy_proxy(row):
    eurusd = row["EUR/USD"]
    usdjpy = row["USD/JPY"]
    gbpusd = row["GBP/USD"]
    usdcad = row["USD/CAD"]
    usdsek = row["USD/SEK"]
    usdchf = row["USD/CHF"]
    return (
        50.14348112
        * eurusd ** -0.576
        * usdjpy ** 0.136
        * gbpusd ** -0.119
        * usdcad ** 0.091
        * usdsek ** 0.042
        * usdchf ** 0.036
    )


def fetch_latest_fx_snapshot():
    rd.open_session()
    raw = rd.get_data(
        universe=list(RICS.values()),
        fields=["BID", "ASK", "CF_LAST", "TRDPRC_1"],
    )
    rows = []
    for target, ric in RICS.items():
        item = raw.loc[raw["Instrument"] == ric].iloc[0]
        rows.append({"instrument": target, "close": mid_from_row(item)})
    snapshot = pd.DataFrame(rows).set_index("instrument")["close"].to_dict()
    snapshot["DXY"] = dxy_proxy(snapshot)
    return snapshot, raw


def generate_signals(snapshot):
    eurusd = snapshot["EUR/USD"]
    usdjpy = snapshot["USD/JPY"]
    dxy = snapshot["DXY"]

    # This one-cell version has no history, so trend is neutral. The full repo
    # script uses historical prices for 20D/60D momentum.
    dxy_cycle = as_score(dxy - 100.0, 8.0)
    risk_off = as_score(POLICY["vix"] - 18.0, 8.0)

    eur_carry = as_score(
        0.5 * (POLICY["ecb_rate"] - POLICY["fed_rate"])
        + 0.5 * (POLICY["de10y"] - POLICY["us10y"]),
        2.5,
    )
    jpy_carry = as_score(
        0.5 * (POLICY["fed_rate"] - POLICY["boj_rate"])
        + 0.5 * (POLICY["us10y"] - POLICY["jp10y"]),
        4.0,
    )
    dxy_carry = as_score(
        0.5 * (POLICY["fed_rate"] - (POLICY["ecb_rate"] + POLICY["boj_rate"]) / 2)
        + 0.5 * (POLICY["us10y"] - (POLICY["de10y"] + POLICY["jp10y"]) / 2),
        3.5,
    )

    rows = [
        {
            "instrument": "EUR/USD",
            "close": eurusd,
            "trend_score": 0.0,
            "carry_policy_score": eur_carry,
            "dxy_cycle_score": -dxy_cycle,
            "news_policy_score": 0.0,
            "risk_sentiment_score": -0.5 * risk_off,
        },
        {
            "instrument": "USD/JPY",
            "close": usdjpy,
            "trend_score": 0.0,
            "carry_policy_score": jpy_carry,
            "dxy_cycle_score": dxy_cycle,
            "news_policy_score": 0.0,
            "risk_sentiment_score": -0.6 * risk_off,
        },
        {
            "instrument": "DXY_PROXY",
            "close": dxy,
            "trend_score": 0.0,
            "carry_policy_score": dxy_carry,
            "dxy_cycle_score": dxy_cycle,
            "news_policy_score": 0.0,
            "risk_sentiment_score": risk_off,
        },
    ]
    signals = pd.DataFrame(rows)
    signals["composite_score"] = (
        0.25 * signals["trend_score"]
        + 0.35 * signals["carry_policy_score"]
        + 0.25 * signals["dxy_cycle_score"]
        + 0.10 * signals["news_policy_score"]
        + 0.05 * signals["risk_sentiment_score"]
    ).clip(-1, 1)
    signals["side"] = signals["composite_score"].apply(side)
    signals["signal_state"] = signals["composite_score"].apply(watch_direction)
    signals["target_weight"] = signals["composite_score"].round(4)
    signals.loc[signals["side"] == "HOLD", "target_weight"] = 0.0
    signals["confidence"] = signals["composite_score"].abs().round(4)
    return signals[
        [
            "instrument",
            "close",
            "side",
            "signal_state",
            "target_weight",
            "confidence",
            "composite_score",
            "trend_score",
            "carry_policy_score",
            "dxy_cycle_score",
            "news_policy_score",
            "risk_sentiment_score",
        ]
    ]


snapshot, raw = fetch_latest_fx_snapshot()
signals = generate_signals(snapshot)

display(HTML("<h2>Raw Refinitiv FX Snapshot</h2>"))
display(raw)
display(HTML("<h2>FX Trading Signals</h2>"))
display(signals)

signals.to_csv("fx_trading_signals_latest.csv", index=False)
signals
