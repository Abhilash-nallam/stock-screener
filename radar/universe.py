"""NSE/BSE equity universes, refresh helpers and cached selection."""
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

NSE_EQUITY_CSV = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_EQUITY_API = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
DATA_DIR = Path("data")
NSE_CACHE = DATA_DIR / "nse_equity_universe.csv"
BSE_CACHE = DATA_DIR / "bse_equity_universe.csv"
REFRESH_META = DATA_DIR / "universe_refresh.json"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"


def _record_refresh(exchange, count):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        status = json.loads(REFRESH_META.read_text(encoding="utf-8")) if REFRESH_META.exists() else {}
    except Exception:
        status = {}
    status[exchange] = {
        "count": int(count),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    REFRESH_META.write_text(json.dumps(status, indent=2), encoding="utf-8")


def read_refresh_status():
    try:
        return json.loads(REFRESH_META.read_text(encoding="utf-8")) if REFRESH_META.exists() else {}
    except Exception:
        return {}


def fetch_nse_universe():
    """Refresh the official NSE EQ security CSV and cache normalised columns."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/csv,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    response = requests.get(NSE_EQUITY_CSV, headers=headers, timeout=35)
    response.raise_for_status()
    raw = pd.read_csv(io.BytesIO(response.content))
    raw.columns = [str(col).strip().upper() for col in raw.columns]

    symbol_col = next((c for c in raw.columns if c == "SYMBOL" or c.endswith("SYMBOL")), None)
    company_col = next((c for c in raw.columns if "COMPANY" in c or "NAME" in c), None)
    series_col = next((c for c in raw.columns if "SERIES" in c), None)
    isin_col = next((c for c in raw.columns if "ISIN" in c), None)
    if not symbol_col or not company_col:
        raise ValueError(f"Unexpected NSE CSV columns: {list(raw.columns)}")
    if series_col:
        raw = raw[raw[series_col].astype(str).str.upper().eq("EQ")]

    out = pd.DataFrame({
        "symbol": raw[symbol_col].astype(str).str.strip().str.upper(),
        "company": raw[company_col].astype(str).str.strip(),
        "exchange": "NSE",
        "sector": "Unknown",
        "isin": raw[isin_col].astype(str).str.strip().str.upper() if isin_col else "",
    })
    out = out[
        out["symbol"].str.fullmatch(r"[A-Z0-9&_-]+", na=False)
        & out["company"].ne("")
    ].drop_duplicates("symbol").sort_values("symbol")
    out["yahoo_symbol"] = out["symbol"] + ".NS"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(NSE_CACHE, index=False)
    _record_refresh("nse", len(out))
    return out.reset_index(drop=True)


def _bse_field(item, names, default=""):
    for name in names:
        value = item.get(name)
        if value is not None and str(value).strip() and str(value).strip().lower() != "nan":
            return str(value).strip()
    return default


def _extract_bse_rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("Table", "table", "data", "Data", "result", "Result", "scrips", "ScripData"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("BSE response did not contain a recognised securities list")


def fetch_bse_universe():
    """Refresh active BSE equity scrips from BSE's public listed-scrip endpoint.

    BSE scrip codes are mapped to Yahoo Finance .BO daily tickers. The public
    endpoint is not a guaranteed data service and may change or rate-limit.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.bseindia.com/",
        "Origin": "https://www.bseindia.com",
    })
    try:
        session.get("https://www.bseindia.com/", timeout=15)
    except requests.RequestException:
        pass

    response = session.get(
        BSE_EQUITY_API,
        params={"Group": "", "scripcode": "", "industry": "", "segment": "Equity", "status": "Active"},
        timeout=35,
    )
    response.raise_for_status()
    rows = _extract_bse_rows(response.json())

    records = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        code = _bse_field(item, (
            "SCRIP_CD", "Scrip_Code", "ScripCode", "scrip_cd", "SCRIPCODE", "scripcode"
        ))
        name = _bse_field(item, (
            "Issuer_Name", "Scrip_Name", "SecurityName", "ISSUER_NAME",
            "Security_Name", "scrip_name", "company_name"
        ))
        isin = _bse_field(item, ("ISIN_NUMBER", "ISIN", "isin_number", "isin")).upper()
        sector = _bse_field(item, ("INDUSTRY", "Industry", "industry"), "Unknown")
        if not code.isdigit() or not name:
            continue
        records.append({
            "symbol": code,
            "company": name,
            "exchange": "BSE",
            "sector": sector or "Unknown",
            "isin": isin,
            "yahoo_symbol": code + ".BO",
        })

    out = pd.DataFrame(records)
    if out.empty:
        raise ValueError(
            "BSE returned no active equity scrips in the expected format. "
            "BSE may have changed its public endpoint; cached list was preserved."
        )
    out = out.drop_duplicates("yahoo_symbol").sort_values("symbol").reset_index(drop=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(BSE_CACHE, index=False)
    _record_refresh("bse", len(out))
    return out


def load_cached_nse_universe():
    return pd.read_csv(NSE_CACHE).fillna("") if NSE_CACHE.exists() else pd.DataFrame()


def load_cached_bse_universe():
    return pd.read_csv(BSE_CACHE).fillna("") if BSE_CACHE.exists() else pd.DataFrame()


def combine_universe(nse, bse=None):
    """Combine NSE and BSE lists; prefer NSE where an ISIN appears on both."""
    frames = []
    if nse is not None and not nse.empty:
        frames.append(nse.copy())
    if bse is not None and not bse.empty:
        required = {"symbol", "company", "exchange", "sector", "yahoo_symbol"}
        if required.issubset(bse.columns):
            frames.append(bse[bse["exchange"].astype(str).str.upper().eq("BSE")].copy())
    if not frames:
        return pd.DataFrame(columns=["symbol", "company", "exchange", "sector", "isin", "yahoo_symbol"])

    combined = pd.concat(frames, ignore_index=True).fillna("")
    if "isin" not in combined.columns:
        combined["isin"] = ""
    combined["isin"] = combined["isin"].astype(str).str.strip().str.upper()
    valid_isin = combined["isin"].ne("") & combined["isin"].str.lower().ne("nan")
    with_isin = combined[valid_isin].drop_duplicates("isin", keep="first")
    without_isin = combined[~valid_isin].drop_duplicates("yahoo_symbol", keep="first")
    result = pd.concat([with_isin, without_isin], ignore_index=True)
    return result.drop_duplicates("yahoo_symbol", keep="first").sort_values(
        ["exchange", "symbol"], ascending=[True, True]
    ).reset_index(drop=True)


def load_cached_combined_universe():
    return combine_universe(load_cached_nse_universe(), load_cached_bse_universe())


def select_scan_universe(universe, limit, as_of=None):
    """Select up to 80% NSE and 20% BSE-exclusive symbols, then fill remaining slots."""
    limit = int(limit)
    if limit not in (250, 500):
        raise ValueError("Scan size must be either 250 or 500")
    if universe is None or universe.empty:
        return pd.DataFrame()
    data = universe.copy()
    nse = data[data["exchange"].astype(str).str.upper().eq("NSE")]
    bse = data[data["exchange"].astype(str).str.upper().eq("BSE")]
    nse_count = min(len(nse), int(limit * 0.8))
    bse_count = min(len(bse), limit - nse_count)
    # Stable within a calendar day; advances across the full sorted exchange list
    # on each new India calendar day, instead of scanning only the first symbols.
    from datetime import date
    day_index = (as_of or date.today()).toordinal()

    def rotating_slice(frame, count, offset):
        if frame.empty or count <= 0:
            return frame.head(0)
        start = offset % len(frame)
        positions = [(start + i) % len(frame) for i in range(min(count, len(frame)))]
        return frame.iloc[positions]

    selected_nse = rotating_slice(nse, nse_count, day_index * nse_count)
    selected_bse = rotating_slice(bse, bse_count, day_index * bse_count)
    selected = pd.concat([selected_nse, selected_bse], ignore_index=True)
    if len(selected) < limit:
        remaining = data[~data["yahoo_symbol"].isin(selected["yahoo_symbol"])]
        selected = pd.concat([selected, rotating_slice(remaining, limit - len(selected), day_index * max(1, limit - len(selected)))], ignore_index=True)
    return selected.drop_duplicates("yahoo_symbol").reset_index(drop=True)
