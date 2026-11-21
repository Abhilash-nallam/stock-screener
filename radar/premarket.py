"""Free-source pre-market context for the Indian cash-equity open.

Yahoo Finance is unofficial and may be delayed. GIFT Nifty is intentionally
reported unavailable unless a verified Yahoo ticker is explicitly configured;
the module never substitutes Nifty spot for GIFT Nifty.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import math
import os
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")

GLOBAL_TICKERS = {
    "DOW": "^DJI",
    "NASDAQ": "^IXIC",
    "SP500": "^GSPC",
}
ASIA_TICKERS = {
    "NIKKEI": "^N225",
    "HANG_SENG": "^HSI",
    "KOSPI": "^KS11",
}


def _history(ticker):
    try:
        frame = yf.download(
            ticker, period="5d", interval="1d", auto_adjust=True,
            progress=False, threads=False, timeout=15,
        )
        if frame is None or frame.empty:
            return pd.Series(dtype=float)
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        if "Close" not in frame:
            return pd.Series(dtype=float)
        series = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        return series[series > 0]
    except Exception:
        return pd.Series(dtype=float)


def _intraday_quote(ticker, now):
    """Return a fresh intraday quote; reject stale or undated daily closes."""
    try:
        frame = yf.download(
            ticker, period="1d", interval="1m", auto_adjust=True,
            progress=False, threads=False, timeout=15,
        )
        if frame is None or frame.empty:
            return None, None
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        if "Close" not in frame:
            return None, None
        close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        if close.empty:
            return None, None
        stamp = pd.Timestamp(close.index[-1])
        stamp = stamp.tz_localize(IST) if stamp.tzinfo is None else stamp.tz_convert(IST)
        age_minutes = (now - stamp.to_pydatetime()).total_seconds() / 60.0
        if age_minutes < -2 or age_minutes > 15:
            return None, None
        price = float(close.iloc[-1])
        if not math.isfinite(price) or price <= 0:
            return None, None
        return price, stamp.isoformat(timespec="minutes")
    except Exception:
        return None, None


def _last_change(series):
    if series is None or len(series) < 2:
        return None
    previous, latest = float(series.iloc[-2]), float(series.iloc[-1])
    if previous <= 0 or not math.isfinite(previous) or not math.isfinite(latest):
        return None
    return (latest / previous - 1.0) * 100.0


def _latest(series):
    if series is None or series.empty:
        return None
    value = float(series.iloc[-1])
    return value if math.isfinite(value) else None


def _fetch_many(tickers):
    values = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(tickers)))) as pool:
        futures = {pool.submit(_history, ticker): key for key, ticker in tickers.items()}
        for future in as_completed(futures):
            try:
                values[futures[future]] = future.result()
            except Exception:
                values[futures[future]] = pd.Series(dtype=float)
    return values


def _direction(value, threshold=0.05):
    if value is None:
        return "unavailable"
    if value > threshold:
        return "positive"
    if value < -threshold:
        return "negative"
    return "flat"


def build_opening_assessment(indicators, checked_at=None):
    """Combine available directional inputs; volatility changes risk, not direction."""
    directional = []
    for key, weight in (
        ("DOW", 0.15), ("NASDAQ", 0.15), ("SP500", 0.15),
        ("ASIA_AVG", 0.20), ("GIFT_GAP_PCT", 0.35),
    ):
        value = indicators.get(key)
        if value is None:
            continue
        directional.append((max(-2.0, min(2.0, float(value))), weight))

    available_weight = sum(weight for _, weight in directional)
    if not directional:
        score = None
        direction = "INSUFFICIENT DATA"
        confidence = 0
    else:
        score = sum(value * weight for value, weight in directional) / available_weight
        coverage = min(1.0, available_weight)
        separation = min(1.0, abs(score) / 0.75)
        confidence = round(coverage * separation * 100)
        # Do not issue a directional bias from one weak or isolated input.
        if coverage < 0.50:
            direction = "INSUFFICIENT DATA"
        elif score >= 0.20:
            direction = "BULLISH BIAS"
        elif score <= -0.20:
            direction = "BEARISH BIAS"
        else:
            direction = "NEUTRAL / MIXED"

    vix = indicators.get("INDIA_VIX")
    if vix is None:
        volatility = "UNAVAILABLE"
        risk_note = "India VIX unavailable; volatility risk cannot be classified."
    elif vix >= 20:
        volatility = "HIGH"
        risk_note = "High volatility regime: reduce position size and avoid chasing opening gaps."
    elif vix >= 15:
        volatility = "ELEVATED"
        risk_note = "VIX is elevated (15+); expect wider swings and stricter risk controls."
    else:
        volatility = "RELATIVELY LOW"
        risk_note = "VIX is below 15; this indicates relatively lower implied volatility, not low risk."

    return {
        "direction": direction,
        "score": round(score, 3) if score is not None else None,
        "confidence": confidence,
        "available_weight": round(available_weight, 2),
        "volatility": volatility,
        "india_vix": round(vix, 2) if vix is not None else None,
        "risk_note": risk_note,
        "checked_at": checked_at or datetime.now(IST).isoformat(timespec="minutes"),
        "indicators": indicators,
        "breadth_status": "Not available as a confirmed full-market measure before 09:15; recheck after the open.",
        "limitations": [
            "Directional score is a heuristic, not a calibrated probability of an up or down open.",
            "Dow, Nasdaq and S&P values are previous completed-session changes, not live US trading.",
            "GIFT Nifty requires a configured, fresh 1-minute quote; stale data and Nifty spot are never substituted.",
            "A directional bias requires at least 50% of the weighted directional inputs to be available.",
            "Confirmed NSE advances/declines breadth is not assumed available at 09:00.",
        ],
    }


def fetch_premarket_snapshot(now=None):
    """Fetch overnight global close, India VIX and optional configured GIFT Nifty."""
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    else:
        current = current.astimezone(IST)

    tickers = {**GLOBAL_TICKERS, **ASIA_TICKERS, "INDIA_VIX": "^INDIAVIX"}
    gift_symbol = os.getenv("GIFT_NIFTY_YAHOO_SYMBOL", "").strip()
    histories = _fetch_many(tickers)

    indicators = {}
    rows = []
    for key in (*GLOBAL_TICKERS.keys(), *ASIA_TICKERS.keys()):
        series = histories.get(key, pd.Series(dtype=float))
        change = _last_change(series)
        indicators[key] = round(change, 3) if change is not None else None
        rows.append({
            "indicator": key.replace("_", " "),
            "value": _latest(series),
            "change_pct": round(change, 2) if change is not None else None,
            "status": _direction(change),
            "source": "Yahoo Finance · latest daily bar; Asian session may still be forming at 09:00 IST",
        })

    asia_values = [indicators.get(key) for key in ASIA_TICKERS]
    asia_values = [value for value in asia_values if value is not None]
    indicators["ASIA_AVG"] = (
        sum(asia_values) / len(asia_values) if asia_values else None
    )

    vix_series = histories.get("INDIA_VIX", pd.Series(dtype=float))
    vix = _latest(vix_series)
    indicators["INDIA_VIX"] = vix
    rows.append({
        "indicator": "INDIA VIX",
        "value": vix,
        "change_pct": round(_last_change(vix_series), 2) if _last_change(vix_series) is not None else None,
        "status": "elevated" if vix is not None and vix >= 15 else "below 15" if vix is not None else "unavailable",
        "source": "Yahoo Finance · previous completed daily session",
    })

    gift_value, gift_as_of = (
        _intraday_quote(gift_symbol, current) if gift_symbol else (None, None)
    )
    nifty_series = _history("^NSEI")
    nifty_close = _latest(nifty_series)
    gift_gap = None
    if gift_value is not None and nifty_close is not None and nifty_close > 0:
        gift_gap = (gift_value / nifty_close - 1.0) * 100.0
    indicators["GIFT_GAP_PCT"] = gift_gap
    rows.append({
        "indicator": "GIFT NIFTY IMPLIED GAP",
        "value": gift_value,
        "change_pct": round(gift_gap, 2) if gift_gap is not None else None,
        "status": _direction(gift_gap),
        "source": (
            f"Yahoo Finance 1-minute quote · {gift_as_of}"
            if gift_value is not None else
            "Unavailable or stale · configure a verified GIFT_NIFTY_YAHOO_SYMBOL"
        ),
    })

    assessment = build_opening_assessment(indicators, current.isoformat(timespec="minutes"))
    assessment["rows"] = rows
    assessment["nifty_previous_close"] = nifty_close
    assessment["gift_symbol_configured"] = bool(gift_symbol)
    assessment["session_time_ist"] = current.strftime("%H:%M")
    return assessment
