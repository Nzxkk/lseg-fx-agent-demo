"""Paste this into Refinitiv Workspace CodeBook to find the usable DXY RIC."""

import pandas as pd
import refinitiv.data as rd

rd.open_session()

candidates = [
    ".DXY",
    "DXY",
    "DXY=",
    "DX=F",
    "USDX=",
    ".USDOLLAR",
    "USDOLLAR",
]

rows = []
for ric in candidates:
    try:
        df = rd.get_data(universe=[ric], fields=["BID", "ASK", "TRDPRC_1", "CF_LAST"])
        row = df.iloc[0].to_dict() if len(df) else {}
        row["RIC"] = ric
        rows.append(row)
    except Exception as exc:
        rows.append({"RIC": ric, "error": str(exc)})

pd.DataFrame(rows)
