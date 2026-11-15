"""NSE cash-market session clock using Asia/Kolkata time.

Holiday table source: NSE India, Market Timings & Holidays, 2026 Equities.
Update this table when NSE publishes the next calendar. Unknown years fail
closed for live recommendations until their holiday calendar is added.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NSE_HOLIDAYS = {
    2026: {
        date(2026, 1, 15): "Municipal Corporation Election - Maharashtra",
        date(2026, 1, 26): "Republic Day",
        date(2026, 3, 3): "Holi",
        date(2026, 3, 26): "Shri Ram Navami",
        date(2026, 3, 31): "Shri Mahavir Jayanti",
        date(2026, 4, 3): "Good Friday",
        date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
        date(2026, 5, 1): "Maharashtra Day",
        date(2026, 5, 28): "Bakri Id",
        date(2026, 6, 26): "Muharram",
        date(2026, 9, 14): "Ganesh Chaturthi",
        date(2026, 10, 2): "Mahatma Gandhi Jayanti",
        date(2026, 10, 20): "Dussehra",
        date(2026, 11, 10): "Diwali-Balipratipada",
        date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
        date(2026, 12, 25): "Christmas",
    }
}

PRE_OPEN_START = time(9, 0)
REGULAR_OPEN = time(9, 15)
REGULAR_CLOSE = time(15, 30)


def _as_ist(value=None):
    if value is None:
        return datetime.now(IST)
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)


def _is_session_day(day):
    if day.weekday() >= 5:
        return False, "Weekend"
    calendar = NSE_HOLIDAYS.get(day.year)
    if calendar is None:
        return False, f"NSE holiday calendar for {day.year} is not configured"
    if day in calendar:
        return False, calendar[day]
    return True, "Regular exchange day"


def next_regular_session(now=None, max_days=370):
    current = _as_ist(now)
    day = current.date()
    for offset in range(max_days + 1):
        candidate = day + timedelta(days=offset)
        valid, reason = _is_session_day(candidate)
        if not valid:
            continue
        opening = datetime.combine(candidate, REGULAR_OPEN, tzinfo=IST)
        if opening > current:
            return opening
    return None


def get_market_status(now=None):
    """Return the NSE cash-equity session status at the supplied/current IST time."""
    current = _as_ist(now)
    day = current.date()
    session_day, reason = _is_session_day(day)
    verified = day.year in NSE_HOLIDAYS

    base = {
        "exchange": "NSE",
        "segment": "Equity / Cash",
        "checked_at": current.isoformat(timespec="seconds"),
        "local_date": day.isoformat(),
        "local_time": current.strftime("%H:%M:%S"),
        "timezone": "Asia/Kolkata",
        "calendar_verified": verified,
        "regular_open": False,
        "phase": "closed",
        "reason": reason,
        "next_open": None,
        "next_open_text": None,
    }
    if not verified:
        base["phase"] = "calendar_unverified"
        base["reason"] = f"NSE holiday calendar for {day.year} is not configured; live recommendations are blocked."
        return base

    if not session_day:
        base["phase"] = "holiday" if day.weekday() < 5 else "weekend"
        nxt = next_regular_session(current)
        base["next_open"] = nxt.isoformat(timespec="minutes") if nxt else None
        base["next_open_text"] = nxt.strftime("%a %d %b %Y, %I:%M %p IST") if nxt else None
        return base

    clock = current.time().replace(tzinfo=None)
    if clock < PRE_OPEN_START:
        base["phase"] = "pre_market"
        base["reason"] = "Before the NSE pre-open session (09:00 IST)."
    elif PRE_OPEN_START <= clock < REGULAR_OPEN:
        base["phase"] = "pre_open"
        base["reason"] = "NSE pre-open session. Regular equity trading has not started."
    elif REGULAR_OPEN <= clock < REGULAR_CLOSE:
        base["phase"] = "open"
        base["regular_open"] = True
        base["reason"] = "NSE regular cash-equity session is open."
    else:
        base["phase"] = "post_market"
        base["reason"] = "NSE regular cash-equity session has closed for today."

    if not base["regular_open"]:
        nxt = next_regular_session(current)
        base["next_open"] = nxt.isoformat(timespec="minutes") if nxt else None
        base["next_open_text"] = nxt.strftime("%a %d %b %Y, %I:%M %p IST") if nxt else None
    return base
