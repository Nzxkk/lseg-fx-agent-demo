"""Paste this into Refinitiv Workspace CodeBook to verify DXY proxy components."""

import pandas as pd
import refinitiv.data as rd

rd.open_session()

components = ["EUR=", "JPY=", "GBP=", "CAD=", "SEK=", "CHF=", ".VIX", "US10YT=RR", "DE10YT=RR", "JP10YT=RR"]

df = rd.get_data(
    universe=components,
    fields=["BID", "ASK", "TRDPRC_1", "CF_LAST"],
)

df
