"""Daily OHLCV and Indian/global benchmark context from Yahoo Finance.

Yahoo/yfinance is an unofficial public data route: availability, delay and
completeness are not guaranteed. Do not use these quotes for order execution.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import yfinance as yf


def fetch_daily_history(symbol, period="1y"):
    try:
        frame = yf.download(
            symbol, period=period, interval="1d", auto_adjust=True,
            progress=False, threads=False, timeout=22
        )
    except Exception:
        return pd.DataFrame()
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.rename(columns=str.title)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not set(needed).issubset(frame.columns):
        return pd.DataFrame()
    frame = frame[needed].apply(pd.to_numeric, errors="coerce").dropna()
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame[(frame.Close > 0) & (frame.Volume >= 0)]


def _one(row):
    symbol = str(row.get("yahoo_symbol", "")).strip()
    if not symbol:
        return None
    try:
        history = fetch_daily_history(symbol)
        if len(history) < 61:
            return None
        return dict(row), history
    except Exception:
        return None


def fetch_many(universe, progress_callback=None, workers=6):
    rows = list(universe.to_dict("records"))
    results = []
    if not rows:
        return results
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 8))) as pool:
        futures = [pool.submit(_one, row) for row in rows]
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                item = future.result()
                if item is not None:
                    results.append(item)
            except Exception:
                pass
            if progress_callback:
                progress_callback(done, len(rows), len(results))
    return results


def _close_series(symbol, period="1y"):
    try:
        frame = yf.download(
            symbol, period=period, interval="1d", auto_adjust=True,
            progress=False, threads=False, timeout=18
        )
        if frame is None or frame.empty:
            return pd.Series(dtype=float)
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        if "Close" not in frame.columns:
            return pd.Series(dtype=float)
        series = pd.to_numeric(frame["Close"], errors="coerce").dropna().sort_index()
        return series
    except Exception:
        return pd.Series(dtype=float)


def _return(series, sessions):
    if series is None or len(series) <= sessions:
        return None
    return float((series.iloc[-1] / series.iloc[-sessions-1] - 1) * 100)


def fetch_market_context():
    """Fetch India indices, global equity benchmarks, volatility, FX and commodities."""
    tickers = {
        "NIFTY": "^NSEI",
        "SENSEX": "^BSESN",
        "SP500": "^GSPC",
        "NASDAQ": "^IXIC",
        "DOW": "^DJI",
        "FTSE": "^FTSE",
        "NIKKEI": "^N225",
        "HANG_SENG": "^HSI",
        "INDIA_VIX": "^INDIAVIX",
        "USDINR": "INR=X",
        "BRENT": "BZ=F",
        "GOLD": "GC=F",
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_close_series, ticker): name for name, ticker in tickers.items()}
        series = {}
        for future in as_completed(futures):
            series[futures[future]] = future.result()

    # This function supplies the daily baseline only. Exclude today's unfinished
    # daily candles while NSE is open; the live Groww quote is handled separately.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    india_date = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    for name, values in list(series.items()):
        if values is not None and not values.empty:
            series[name] = values[[pd.Timestamp(index).date() < india_date for index in values.index]]

    nifty = series.get("NIFTY", pd.Series(dtype=float))
    empty = {
        "regime": "unknown", "global_risk": "unknown",
        "nifty_change_1d": None, "nifty_change_5d": None,
        "nifty_ret20_pct": None, "nifty_ret60_pct": None, "nifty_ret120_pct": None,
        "nifty_above_ema200": None, "data_date": None, "benchmarks": {},
        "global_positive_count": 0, "global_count": 0,
    }
    if len(nifty) < 30:
        return empty

    e20 = nifty.ewm(span=20, adjust=False).mean().iloc[-1]
    e50 = nifty.ewm(span=50, adjust=False).mean().iloc[-1]
    e200 = nifty.ewm(span=200, adjust=False).mean().iloc[-1] if len(nifty) >= 200 else None
    day = _return(nifty, 1)
    week = _return(nifty, 5)
    above200 = bool(nifty.iloc[-1] > e200) if e200 is not None else None
    bullish = nifty.iloc[-1] > e20 > e50 and week is not None and week > 0 and above200 is not False
    bearish = nifty.iloc[-1] < e20 < e50 and week is not None and week < 0
    regime = "bullish" if bullish else "bearish" if bearish else "mixed"

    global_indices = ["SP500", "NASDAQ", "DOW", "FTSE", "NIKKEI", "HANG_SENG"]
    global_weekly = []
    benchmarks = {}
    for name, values in series.items():
        if values is None or len(values) < 7:
            continue
        d1, d5, d20 = _return(values, 1), _return(values, 5), _return(values, 20)
        benchmarks[name] = {
            "daily_pct": round(d1, 2) if d1 is not None else None,
            "weekly_pct": round(d5, 2) if d5 is not None else None,
            "monthly_pct": round(d20, 2) if d20 is not None else None,
        }
        if name in global_indices and d5 is not None:
            global_weekly.append(d5)

    global_avg = sum(global_weekly) / len(global_weekly) if global_weekly else None
    if global_avg is None or len(global_weekly) < 3:
        global_risk = "unknown"
    elif global_avg >= 0.4:
        global_risk = "risk_on"
    elif global_avg <= -0.75:
        global_risk = "risk_off"
    else:
        global_risk = "mixed"

    return {
        "regime": regime,
        "global_risk": global_risk,
        "nifty_change_1d": round(day, 2) if day is not None else None,
        "nifty_change_5d": round(week, 2) if week is not None else None,
        "nifty_ret20_pct": round(_return(nifty, 20), 2) if _return(nifty, 20) is not None else None,
        "nifty_ret60_pct": round(_return(nifty, 60), 2) if _return(nifty, 60) is not None else None,
        "nifty_ret120_pct": round(_return(nifty, 120), 2) if _return(nifty, 120) is not None else None,
        "nifty_above_ema200": above200,
        "data_date": str(nifty.index[-1])[:10],
        "benchmarks": benchmarks,
        "global_positive_count": sum(x > 0 for x in global_weekly),
        "global_count": len(global_weekly),
    }


def fetch_nifty():
    """Legacy helper retained for compatibility."""
    return fetch_daily_history("^NSEI")
