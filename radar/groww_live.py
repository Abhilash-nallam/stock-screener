"""Read-only Groww live market-data adapter.

No order APIs are called. Requires an active Groww Trading API subscription
for the Live Data and Historical Candle endpoints.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import os
import re
import time
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://api.groww.in"
IST = ZoneInfo("Asia/Kolkata")
TIMEOUT = 12


class LiveDataUnavailable(RuntimeError):
    pass


def _payload(response, label):
    try:
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        raise LiveDataUnavailable(f"Groww {label} request failed: {exc}") from exc
    if not isinstance(body, dict) or body.get("status") != "SUCCESS":
        detail = body.get("error", {}).get("message") if isinstance(body, dict) else None
        raise LiveDataUnavailable(f"Groww {label} did not return SUCCESS: {detail or body}")
    return body.get("payload") or {}


def create_access_token(api_key=None, api_secret=None):
    """Generate a session token using Groww's API-key approval flow."""
    api_key = (api_key or os.getenv("GROWW_API_KEY", "")).strip()
    api_secret = (api_secret or os.getenv("GROWW_API_SECRET", "")).strip()
    if not api_key or not api_secret:
        raise LiveDataUnavailable(
            "Live quotes are not configured. Add GROWW_ACCESS_TOKEN, or GROWW_API_KEY "
            "and GROWW_API_SECRET, to GitHub Actions secrets."
        )
    timestamp = str(int(time.time()))
    checksum = hashlib.sha256((api_secret + timestamp).encode("utf-8")).hexdigest()
    try:
        response = requests.post(
            f"{BASE_URL}/v1/token/api/access",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"key_type": "approval", "checksum": checksum, "timestamp": timestamp},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        raise LiveDataUnavailable(
            "Groww could not create a session token. Check the API key/secret and approve "
            "today's API session on Groww Cloud API Keys."
        ) from exc
    token = body.get("token") if isinstance(body, dict) else None
    if not token:
        detail = body.get("error", {}).get("message") if isinstance(body, dict) else None
        raise LiveDataUnavailable(
            "Groww did not issue a session token. Today's API-key approval may be missing. "
            + str(detail or "")
        )
    return str(token)


class GrowwLiveClient:
    def __init__(self, access_token=None, session=None):
        self.token = (access_token or os.getenv("GROWW_ACCESS_TOKEN", "")).strip()
        if not self.token:
            self.token = create_access_token()
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "X-API-VERSION": "1.0",
            "User-Agent": "IndiaStockRadar/3.0",
        })

    def _get_payload(self, path, params, label):
        try:
            response = self.session.get(
                f"{BASE_URL}{path}", params=params, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            raise LiveDataUnavailable(f"Groww {label} network error: {exc}") from exc
        return _payload(response, label)

    def get_ltp(self, exchange_symbols):
        payload = self._get_payload(
            "/v1/live-data/ltp",
            {"segment": "CASH", "exchange_symbols": ",".join(exchange_symbols)},
            "LTP",
        )
        return {str(key): float(value) for key, value in payload.items() if _is_number(value)}

    def get_ohlc(self, exchange_symbols):
        payload = self._get_payload(
            "/v1/live-data/ohlc",
            {"segment": "CASH", "exchange_symbols": ",".join(exchange_symbols)},
            "OHLC",
        )
        return {str(key): parse_ohlc(value) for key, value in payload.items()}

    def get_quote(self, trading_symbol):
        payload = self._get_payload(
            "/v1/live-data/quote",
            {"exchange": "NSE", "segment": "CASH", "trading_symbol": trading_symbol},
            "quote",
        )
        return payload

    def get_5m_candles(self, trading_symbol, start_time, end_time):
        payload = self._get_payload(
            "/v1/historical/candles",
            {
                "exchange": "NSE",
                "segment": "CASH",
                "groww_symbol": f"NSE-{trading_symbol}",
                "start_time": start_time,
                "end_time": end_time,
                "candle_interval": "5minute",
            },
            "5-minute candles",
        )
        candles = payload.get("candles", [])
        return candles if isinstance(candles, list) else []


def _is_number(value):
    try:
        return float(value) == float(value)
    except (TypeError, ValueError):
        return False


def parse_ohlc(value):
    """Parse Groww's OHLC object or its documented {open:...,high:...} string."""
    if isinstance(value, dict):
        source = value
    elif isinstance(value, str):
        source = {
            key.lower(): raw
            for key, raw in re.findall(
                r"([A-Za-z_]+)\s*:\s*([-+]?\d+(?:\.\d+)?|null)",
                value,
            )
        }
    else:
        return {}
    result = {}
    for key in ("open", "high", "low", "close"):
        try:
            parsed = source.get(key)
            if parsed is not None and str(parsed).lower() != "null":
                result[key] = float(parsed)
        except (TypeError, ValueError):
            continue
    return result


def fetch_live_snapshots(client, symbols, batch_size=50):
    """Fetch current LTP and current-session OHLC for a set of NSE symbols."""
    unique = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
    ltp, ohlc = {}, {}
    for offset in range(0, len(unique), min(50, max(1, int(batch_size)))):
        chunk = unique[offset:offset + min(50, max(1, int(batch_size)))]
        exchange_symbols = [f"NSE_{symbol}" for symbol in chunk]
        ltp.update(client.get_ltp(exchange_symbols))
        ohlc.update(client.get_ohlc(exchange_symbols))
        # Groww publishes a 10 requests/second Live Data rate limit.
        time.sleep(0.12)
    fetched_at = datetime.now(IST)
    snapshots = {}
    for symbol in unique:
        key = f"NSE_{symbol}"
        if key in ltp and key in ohlc:
            snapshots[symbol] = {
                "price": ltp[key],
                "ohlc": ohlc[key],
                "received_at": fetched_at,
                "provider": "Groww Live Data API",
            }
    return snapshots


def _candle_timestamp(value):
    try:
        if isinstance(value, (int, float)):
            epoch = float(value)
            if epoch > 10_000_000_000:
                epoch /= 1000
            return datetime.fromtimestamp(epoch, tz=ZoneInfo("UTC")).astimezone(IST)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed.astimezone(IST)
    except Exception:
        return None


def normalise_5m_candles(rows, now=None):
    """Convert Groww candle arrays into completed 5-minute OHLCV rows."""
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    else:
        current = current.astimezone(IST)
    minute_floor = (current.minute // 5) * 5
    completed_before = current.replace(minute=minute_floor, second=0, microsecond=0)
    result = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        stamp = _candle_timestamp(row[0])
        if stamp is None or stamp >= completed_before:
            continue
        try:
            candle = {
                "time": stamp,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            if candle["close"] > 0 and candle["volume"] >= 0:
                result.append(candle)
        except (TypeError, ValueError):
            continue
    return sorted(result, key=lambda item: item["time"])


def fetch_candidate_detail(client, symbol, now=None):
    """Get quote and 5-minute candles for one shortlisted NSE instrument."""
    current = now or datetime.now(IST)
    current = current.astimezone(IST) if current.tzinfo else current.replace(tzinfo=IST)
    start = current.replace(hour=9, minute=15, second=0, microsecond=0)
    quote = client.get_quote(symbol)
    raw_candles = client.get_5m_candles(
        symbol,
        start.strftime("%Y-%m-%d %H:%M:%S"),
        current.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return {
        "quote": quote,
        "candles": normalise_5m_candles(raw_candles, current),
    }
