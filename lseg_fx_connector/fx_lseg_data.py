"""LSEG/Refinitiv Data Library adapter for the FX macro-news demo.

This module is optional. It imports ``lseg.data`` or legacy ``refinitiv.data``
only when called, so the offline CSV/sample workflow keeps working on machines
without Workspace libraries installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_RIC_MAP = {
    "EUR/USD": "EUR=",
    "USD/JPY": "JPY=",
    "DXY": ".DXY",
    "GBP/USD": "GBP=",
    "USD/CAD": "CAD=",
    "USD/SEK": "SEK=",
    "USD/CHF": "CHF=",
    "vix": ".VIX",
    "us10y": "US10YT=RR",
    "de10y": "DE10YT=RR",
    "jp10y": "JP10YT=RR",
}

DEFAULT_POLICY_RATES = {
    "fed_rate": 5.25,
    "ecb_rate": 3.75,
    "boj_rate": 0.25,
    "us10y": 4.25,
    "de10y": 2.50,
    "jp10y": 1.00,
    "vix": 18.0,
}


def load_ric_map(path: str | Path | None = None) -> dict[str, str]:
    """Load a JSON RIC mapping override and merge it into the defaults."""
    mapping = DEFAULT_RIC_MAP.copy()
    if path is None:
        return mapping
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("RIC map JSON must be an object")
    mapping.update({str(key): str(value) for key, value in raw.items()})
    return mapping


def load_policy_rates(path: str | Path | None = None) -> dict[str, float]:
    """Load latest policy-rate overrides from JSON.

    JSON example:
      {"fed_rate": 5.25, "ecb_rate": 3.75, "boj_rate": 0.25}
    """
    rates = DEFAULT_POLICY_RATES.copy()
    if path is None:
        return rates
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("policy rates JSON must be an object")
    for key in rates:
        if key in raw:
            rates[key] = float(raw[key])
    return rates


def fetch_lseg_market_data(
    start: str,
    end: str,
    ric_map: dict[str, str] | None = None,
    policy_rates: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Fetch FX, DXY, VIX, and yield history with LSEG/Refinitiv Data Library."""
    rd, _library_name = _import_data_library()

    mapping = ric_map or DEFAULT_RIC_MAP
    rates = policy_rates or DEFAULT_POLICY_RATES
    universe = list(dict.fromkeys(mapping.values()))

    try:
        rd.open_session()
        try:
            raw = rd.get_history(
                universe=universe,
                fields=["TRDPRC_1", "BID", "ASK"],
                interval="1D",
                start=start,
                end=end,
            )
        except Exception as exc:  # noqa: BLE001 - convert vendor/proxy errors to user-facing diagnostics
            raise RuntimeError(_friendly_lseg_error(exc, "历史行情")) from exc
    finally:
        try:
            rd.close_session()
        except Exception:
            pass

    market = normalize_lseg_history(raw, mapping)
    if "DXY" not in market or market["DXY"].dropna().empty:
        market["DXY"] = build_dxy_proxy(market)
    for column, value in rates.items():
        if column in market:
            market[column] = _sanitize_macro_series(market[column], fallback=float(value), column=column)
        else:
            market[column] = float(value)
    required = ["EUR/USD", "USD/JPY", "DXY", "vix", "us10y", "de10y", "jp10y"]
    missing = [column for column in required if column not in market or market[column].dropna().empty]
    if missing:
        raise RuntimeError(
            "LSEG returned no usable data for columns: "
            f"{missing}. Check your entitlements and RIC map."
        )
    return market.ffill().dropna(subset=["EUR/USD", "USD/JPY", "DXY"])


def _sanitize_macro_series(series: pd.Series, fallback: float, column: str) -> pd.Series:
    """Keep usable macro series; otherwise replace with a configured fallback."""
    numeric = pd.to_numeric(series, errors="coerce")
    if column == "vix":
        usable = numeric.where((numeric > 5) & (numeric < 100))
    elif column in {"us10y", "de10y", "jp10y"}:
        # Yield RICs should be percentage yields. If the account returns bond
        # prices around 98-100, treat them as unusable for carry scoring.
        usable = numeric.where((numeric > -2) & (numeric < 20))
    else:
        usable = numeric

    if usable.dropna().empty:
        return pd.Series(fallback, index=series.index, name=series.name)
    return usable.ffill().fillna(fallback)


def build_dxy_proxy(market: pd.DataFrame) -> pd.Series:
    """Build a DXY proxy from the six ICE U.S. Dollar Index currency legs.

    Formula:
      50.14348112 * EURUSD^-0.576 * USDJPY^0.136 * GBPUSD^-0.119
      * USDCAD^0.091 * USDSEK^0.042 * USDCHF^0.036
    """
    required = ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CAD", "USD/SEK", "USD/CHF"]
    missing = [column for column in required if column not in market or market[column].dropna().empty]
    if missing:
        raise RuntimeError(
            "Direct DXY is unavailable and DXY proxy components are missing: "
            f"{missing}. Check RIC mapping for GBP=, CAD=, SEK=, CHF=."
        )

    frame = market[required].apply(pd.to_numeric, errors="coerce").ffill()
    proxy = (
        50.14348112
        * frame["EUR/USD"].pow(-0.576)
        * frame["USD/JPY"].pow(0.136)
        * frame["GBP/USD"].pow(-0.119)
        * frame["USD/CAD"].pow(0.091)
        * frame["USD/SEK"].pow(0.042)
        * frame["USD/CHF"].pow(0.036)
    )
    proxy.name = "DXY"
    return proxy


def normalize_lseg_history(raw: pd.DataFrame, ric_map: dict[str, str]) -> pd.DataFrame:
    """Normalize common LSEG get_history dataframe shapes into demo columns."""
    if raw is None or raw.empty:
        raise RuntimeError("LSEG get_history returned an empty dataframe")

    frame = raw.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        date_column = _find_column(frame, ("date", "datetime", "timestamp"))
        if date_column:
            frame[date_column] = pd.to_datetime(frame[date_column])
            frame = frame.set_index(date_column)
        else:
            frame.index = pd.to_datetime(frame.index)
    frame = frame.sort_index()

    output = pd.DataFrame(index=pd.DatetimeIndex(frame.index))
    for target, ric in ric_map.items():
        series = _extract_ric_series(frame, ric)
        if series is not None:
            output[target] = pd.to_numeric(series, errors="coerce")
    output.index.name = "date"
    return output


def fetch_lseg_reuters_news(
    query: str,
    count: int = 100,
) -> pd.DataFrame:
    """Fetch Reuters/LSEG news headlines when the account is entitled.

    The LSEG library has changed news access paths across versions, so this
    tries the simple Access-layer path first and then a Content-layer path.
    """
    rd, library_name = _import_data_library()

    try:
        rd.open_session()
        try:
            raw = _get_news_headlines(rd, library_name=library_name, query=query, count=count)
        except Exception as exc:  # noqa: BLE001 - convert vendor/proxy errors to user-facing diagnostics
            raise RuntimeError(_friendly_lseg_error(exc, "Reuters/LSEG 新闻")) from exc
    finally:
        try:
            rd.close_session()
        except Exception:
            pass

    return normalize_lseg_news(raw)


def _friendly_lseg_error(exc: Exception, data_type: str) -> str:
    message = str(exc)
    lower = message.lower()
    if "session is not opened" in lower or "no proxy address identified" in lower:
        return (
            f"LSEG {data_type}请求失败：Workspace/Eikon 本地会话没有打开。"
            "请先打开 Refinitiv Workspace/Eikon 并完成登录，再重新运行。"
        )
    if "localhost:9000" in lower or "localhost:9060" in lower or "connection refused" in lower or "operation not permitted" in lower:
        return (
            f"LSEG {data_type}请求失败：无法连接 Workspace/Eikon 本地 API Proxy "
            "(localhost:9000/9060)。请确认桌面端已打开、已登录，并允许本地 API 访问。"
        )
    if "401" in lower or "403" in lower or "permission" in lower or "entitlement" in lower:
        return f"LSEG {data_type}请求失败：账号可能没有对应 RIC、历史行情或新闻权限。原始错误：{message[:500]}"
    return f"LSEG {data_type}请求失败：{message[:800]}"


def normalize_lseg_news(raw: Any) -> pd.DataFrame:
    """Normalize LSEG news output to timestamp/headline/body/topic."""
    if hasattr(raw, "data") and hasattr(raw.data, "df"):
        frame = raw.data.df.copy()
    elif isinstance(raw, pd.DataFrame):
        frame = raw.copy()
    else:
        frame = pd.DataFrame(raw)

    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "headline", "body", "topic"])

    columns_lower = {str(column).lower(): column for column in frame.columns}
    timestamp_col = _first_existing(
        columns_lower,
        ("timestamp", "versioncreated", "created", "date", "storytime", "firstcreated"),
    )
    headline_col = _first_existing(
        columns_lower,
        ("headline", "text", "storyheadline", "documenttitle", "title"),
    )
    body_col = _first_existing(columns_lower, ("body", "story", "snippet", "summary"))

    if headline_col is None:
        raise RuntimeError(f"Cannot find headline column in LSEG news output: {list(frame.columns)}")
    if timestamp_col is None:
        frame["timestamp"] = pd.Timestamp.utcnow().tz_localize(None)
        timestamp_col = "timestamp"

    normalized = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(frame[timestamp_col]).dt.tz_localize(None),
            "headline": frame[headline_col].astype(str),
            "body": frame[body_col].astype(str) if body_col else "",
            "topic": "reuters_fx_macro",
        }
    )
    return normalized.sort_values("timestamp").reset_index(drop=True)


def _import_data_library() -> tuple[Any, str]:
    try:
        import lseg.data as rd
        return rd, "lseg"
    except ImportError:
        pass

    try:
        import refinitiv.data as rd
        return rd, "refinitiv"
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: install `lseg-data` or use the Refinitiv Workspace "
            "CodeBook Python environment that has `refinitiv.data`."
        ) from exc


def _get_news_headlines(rd: Any, library_name: str, query: str, count: int) -> Any:
    if hasattr(rd, "news") and hasattr(rd.news, "get_headlines"):
        return rd.news.get_headlines(query=query, count=count)

    try:
        if library_name == "lseg":
            from lseg.data.content import news
        else:
            from refinitiv.data.content import news
    except ImportError as exc:
        raise RuntimeError(
            "This Data Library version does not expose a news headline helper. "
            "Use Workspace export CSV or update the Workspace Python library."
        ) from exc

    if hasattr(news, "headlines") and hasattr(news.headlines, "Definition"):
        return news.headlines.Definition(query=query, count=count).get_data()
    if hasattr(news, "Definition"):
        return news.Definition(query=query, count=count).get_data()
    raise RuntimeError("Cannot find a supported LSEG news headline API in this lseg-data version.")


def _extract_ric_series(frame: pd.DataFrame, ric: str) -> pd.Series | None:
    if isinstance(frame.columns, pd.MultiIndex):
        for level in range(frame.columns.nlevels):
            if ric not in frame.columns.get_level_values(level):
                continue
            selected = frame.xs(ric, axis=1, level=level, drop_level=True)
            return _first_price_series(selected)
        return None

    instrument_col = _find_column(frame, ("instrument", "ric"))
    if instrument_col and ric in set(frame[instrument_col].astype(str)):
        selected = frame.loc[frame[instrument_col].astype(str) == ric]
        return _first_price_series(selected)

    if ric in frame.columns:
        return frame[ric]
    return _first_price_series(frame) if len(frame.columns) <= 4 else None


def _first_price_series(frame: pd.DataFrame) -> pd.Series | None:
    if "BID" in frame.columns and "ASK" in frame.columns:
        bid = pd.to_numeric(frame["BID"], errors="coerce")
        ask = pd.to_numeric(frame["ASK"], errors="coerce")
        mid = (bid + ask) / 2.0
        if mid.notna().any():
            return mid

    for name in ("TRDPRC_1", "Close", "CLOSE", "BID", "ASK", "VALUE", "Value"):
        if name in frame.columns:
            series = pd.to_numeric(frame[name], errors="coerce")
            if series.notna().any():
                return series
    numeric = frame.select_dtypes(include=["number"])
    if not numeric.empty:
        for column in numeric.columns:
            if numeric[column].notna().any():
                return numeric[column]
    return None


def _find_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    columns_lower = {str(column).lower(): column for column in frame.columns}
    return _first_existing(columns_lower, names)


def _first_existing(columns_lower: dict[str, Any], names: tuple[str, ...]) -> Any | None:
    for name in names:
        if name.lower() in columns_lower:
            return columns_lower[name.lower()]
    return None
