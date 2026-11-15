"""Intraday confirmation layer for live stock-watchlist candidates.

Combines a previously completed daily technical score with a fresh Groww quote
and completed 5-minute candles. This produces watch/avoid signals, not orders.
"""
from datetime import datetime, timezone
import math
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CANDLE_INTERVAL_SECONDS = 300
MAX_NIFTY_ALIGNMENT_SECONDS = 600


def _number(value, default=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _clip(value, low=0.0, high=100.0):
    return max(low, min(high, float(value)))


def _trade_time_epoch(value):
    parsed = _number(value)
    if parsed is None:
        return None
    if parsed > 10_000_000_000:
        parsed /= 1000.0
    try:
        return datetime.fromtimestamp(parsed, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def build_live_signal(
    daily_row, snapshot, detail, nifty_change_pct=None, now=None,
    nifty_candle_end_time=None,
):
    """Return a live-confirmation result for one daily-ranked candidate."""
    current = now or datetime.now(IST)
    current = current.astimezone(IST) if current.tzinfo else current.replace(tzinfo=IST)

    quote = (detail or {}).get("quote") or {}
    candles = (detail or {}).get("candles") or []
    live_price = _number((snapshot or {}).get("price"))
    previous_close = _number(daily_row.get("price"))
    ohlc = (snapshot or {}).get("ohlc") or {}
    day_open = _number(ohlc.get("open"))
    score_daily = _number(daily_row.get("score"), 0.0)

    if live_price is None or live_price <= 0 or previous_close is None or previous_close <= 0:
        return {"live_status": "REJECT — invalid live/previous-close price", "live_eligible": False}

    source_label = str((detail or {}).get("provider") or (snapshot or {}).get("provider") or "")
    timestamp_value = quote.get("last_trade_time") or quote.get("last_update_time")
    last_trade_dt = _trade_time_epoch(timestamp_value)
    quote_age = (current.astimezone(timezone.utc) - last_trade_dt).total_seconds() if last_trade_dt else None
    # Yahoo public intraday candles may be delayed. Do not call them real-time;
    # allow up to 20 minutes but label the exact candle time and provider.
    max_age = _number((detail or {}).get("max_age_seconds"), 600 if "Yahoo" in source_label else 180)
    quote_fresh = quote_age is not None and -5 <= quote_age <= max_age

    candle_times = [item.get("time") for item in candles[-6:]]
    candles_contiguous = len(candle_times) == 6 and all(
        candle_times[i] is not None
        and candle_times[i + 1] is not None
        and (candle_times[i + 1] - candle_times[i]).total_seconds() == CANDLE_INTERVAL_SECONDS
        for i in range(5)
    )
    candidate_candle_end = (
        candles[-1]["time"] + __import__("datetime").timedelta(seconds=CANDLE_INTERVAL_SECONDS)
        if candles and candles[-1].get("time") is not None else None
    )
    nifty_alignment_ok = True
    if nifty_candle_end_time is not None and candidate_candle_end is not None:
        delta_seconds = abs((candidate_candle_end - nifty_candle_end_time).total_seconds())
        nifty_alignment_ok = delta_seconds <= MAX_NIFTY_ALIGNMENT_SECONDS

    day_change = (live_price / previous_close - 1.0) * 100.0
    gap_pct = (day_open / previous_close - 1.0) * 100.0 if day_open else None
    intraday_change = (live_price / day_open - 1.0) * 100.0 if day_open else None
    relative_to_nifty = (
        day_change - float(nifty_change_pct)
        if nifty_change_pct is not None and _number(nifty_change_pct) is not None
        else None
    )

    result = {
        "live_price": round(live_price, 2),
        "live_change_pct": round(day_change, 2),
        "live_gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
        "live_intraday_pct": round(intraday_change, 2) if intraday_change is not None else None,
        "live_relative_strength_pct": round(relative_to_nifty, 2) if relative_to_nifty is not None else None,
        "live_quote_age_seconds": round(quote_age, 1) if quote_age is not None else None,
        "live_quote_time": last_trade_dt.astimezone(IST).strftime("%H:%M:%S IST") if last_trade_dt else "unavailable",
        "live_provider": source_label or "Unknown intraday source",
        "live_timestamp_label": str((detail or {}).get("timestamp_label") or "last trade"),
        "live_max_age_seconds": max_age,
        "live_vwap": None,
        "live_vwap_distance_pct": None,
        "live_5m_momentum_pct": None,
        "live_score": 0.0,
        "live_status": "WAIT — intraday confirmation pending",
        "live_reason": "",
        "live_eligible": False,
        "live_entry_low": None,
        "live_entry_high": None,
        "live_stop": None,
        "live_target1": None,
        "live_target2": None,
        "live_completed_5m_candles": len(candles),
    }

    reasons = []
    if not quote_fresh:
        reasons.append(f"Intraday timestamp is missing or older than {int(max_age / 60)} minutes")
    if len(candles) < 6:
        reasons.append(f"Only {len(candles)} completed 5-minute candles; need at least 6 for volume confirmation")
    elif not candles_contiguous:
        reasons.append("Last six 5-minute candles are not consecutive; intraday continuity is unverified")
    if not nifty_alignment_ok:
        reasons.append("Stock and Nifty 5-minute candles are too far apart in time")
    if day_open is None or day_open <= 0:
        reasons.append("Live session opening price is unavailable")

    if len(candles) < 6 or not candles_contiguous or not nifty_alignment_ok or day_open is None or day_open <= 0:
        result["live_reason"] = "; ".join(reasons) or "Intraday inputs unavailable"
        result["live_status"] = "WAIT — insufficient intraday data"
        return result

    volumes = [_number(item.get("volume"), 0.0) for item in candles]
    typical_prices = [
        (_number(item.get("high"), 0.0) + _number(item.get("low"), 0.0) + _number(item.get("close"), 0.0)) / 3.0
        for item in candles
    ]
    volume_total = sum(max(0.0, value or 0.0) for value in volumes)
    if volume_total <= 0:
        reasons.append("No usable 5-minute volume for VWAP")
        result["live_reason"] = "; ".join(reasons)
        result["live_status"] = "WAIT — volume confirmation unavailable"
        return result

    vwap = sum(price * max(0.0, volume or 0.0) for price, volume in zip(typical_prices, volumes)) / volume_total
    vwap_distance = (live_price / vwap - 1.0) * 100.0 if vwap > 0 else None

    last_three = candles[-3:]
    first_close = _number(last_three[0].get("close"))
    last_close = _number(last_three[-1].get("close"))
    momentum_3 = (last_close / first_close - 1.0) * 100.0 if first_close and last_close else None
    green_count = sum(
        1 for item in last_three
        if (_number(item.get("close"), 0.0) > _number(item.get("open"), 0.0))
    )
    last_candle_green = _number(last_three[-1].get("close"), 0.0) > _number(last_three[-1].get("open"), 0.0)

    # Compare the most recent three completed 5m bars with the preceding three
    # only when six or more are present; don't invent an intraday volume baseline.
    volume_confirmation = None
    if len(candles) >= 6:
        prior_volume = sum(max(0.0, x or 0.0) for x in volumes[-6:-3]) / 3.0
        recent_volume = sum(max(0.0, x or 0.0) for x in volumes[-3:]) / 3.0
        volume_confirmation = recent_volume >= prior_volume * 1.05 if prior_volume > 0 else None

    vwap_score = 20.0 if vwap_distance is None else _clip(50 + vwap_distance * 25)
    momentum_score = 50.0 if momentum_3 is None else _clip(50 + momentum_3 * 35)
    relative_score = 50.0 if relative_to_nifty is None else _clip(50 + relative_to_nifty * 8)
    if gap_pct is None:
        gap_score = 50.0
    elif -1.0 <= gap_pct <= 2.0:
        gap_score = 90.0
    elif -2.0 <= gap_pct <= 3.5:
        gap_score = 68.0
    elif gap_pct > 3.5:
        gap_score = 20.0
    else:
        gap_score = 15.0
    daily_risk = str(daily_row.get("risk", "")).strip().lower()
    if daily_risk == "high":
        reasons.append("Daily model risk is High; excluded from live-confirmed picks")

    live_score = (
        0.45 * _clip(score_daily)
        + 0.20 * vwap_score
        + 0.15 * momentum_score
        + 0.10 * relative_score
        + 0.10 * gap_score
    )
    result.update({
        "live_vwap": round(vwap, 2),
        "live_vwap_distance_pct": round(vwap_distance, 3) if vwap_distance is not None else None,
        "live_5m_momentum_pct": round(momentum_3, 3) if momentum_3 is not None else None,
        "live_score": round(live_score, 1),
        "live_volume_confirmation": volume_confirmation,
        "live_recent_green_5m": green_count,
    })

    if not quote_fresh:
        reasons.append("Intraday timestamp freshness check failed")
    if vwap_distance is None or vwap_distance <= 0:
        reasons.append("Price is not above session VWAP")
    if momentum_3 is None or momentum_3 <= 0:
        reasons.append("Last three completed 5-minute candles lack positive momentum")
    if not last_candle_green:
        reasons.append("Most recent completed 5-minute candle is not bullish")
    if gap_pct is not None and gap_pct > 3.5:
        reasons.append("Opening gap is too large; avoid chasing")
    if gap_pct is not None and gap_pct < -2.0:
        reasons.append("Opening gap is materially negative")
    if relative_to_nifty is not None and relative_to_nifty < -0.15:
        reasons.append("Underperforming Nifty since previous close")
    if nifty_change_pct is not None and _number(nifty_change_pct) is not None:
        if float(nifty_change_pct) < -0.75 and (relative_to_nifty is None or relative_to_nifty < 0.5):
            reasons.append("Broad Nifty sell-off; stock has not shown enough relative strength")
    if volume_confirmation is not True:
        reasons.append("Recent 5-minute volume is not confirmed as expanding")
    if live_score < 68:
        reasons.append("Live composite score is below the confirmation threshold")

    # At least 6 completed candles, expanding volume, a recent provider timestamp,
    # price above VWAP, positive short-term momentum and a non-extreme opening gap are mandatory.
    hard_gates = (
        quote_fresh
        and len(candles) >= 6
        and volume_confirmation is True
        and vwap_distance is not None and vwap_distance > 0
        and momentum_3 is not None and momentum_3 > 0
        and last_candle_green
        and (gap_pct is None or -2.0 <= gap_pct <= 3.5)
        and (relative_to_nifty is None or relative_to_nifty >= -0.15)
        and daily_risk != "high"
        and nifty_alignment_ok
        and live_score >= 68
        and not (
            nifty_change_pct is not None
            and _number(nifty_change_pct) is not None
            and float(nifty_change_pct) < -0.75
            and (relative_to_nifty is None or relative_to_nifty < 0.5)
        )
    )

    atr_pct = _number(daily_row.get("atr_pct"), 2.5)
    atr_value = live_price * max(0.8, min(7.0, atr_pct or 2.5)) / 100.0
    result["live_entry_low"] = round(max(0.01, live_price - 0.10 * atr_value), 2)
    result["live_entry_high"] = round(live_price + 0.10 * atr_value, 2)
    result["live_stop"] = round(max(0.01, live_price - 1.25 * atr_value), 2)
    result["live_target1"] = round(live_price + 1.25 * atr_value, 2)
    result["live_target2"] = round(live_price + 2.0 * atr_value, 2)

    result["live_eligible"] = bool(hard_gates)
    if hard_gates:
        result["live_status"] = "CONFIRMED WATCHLIST — verify before entry"
        if not reasons:
            reasons.append("Daily strength + fresh quote + price above VWAP + positive 5-minute momentum")
    else:
        result["live_status"] = "WAIT — live confirmation not complete"
    result["live_reason"] = "; ".join(dict.fromkeys(reasons)) or "Live conditions passed current filters"
    return result
