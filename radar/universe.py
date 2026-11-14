import io, requests, pandas as pd
from pathlib import Path
NSE_EQUITY_CSV="https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
CACHE=Path("data/nse_equity_universe.csv")
def fetch_nse_universe():
    headers={"User-Agent":"Mozilla/5.0 Chrome/120 Safari/537.36","Accept":"text/csv,*/*","Referer":"https://www.nseindia.com/"}
    r=requests.get(NSE_EQUITY_CSV,headers=headers,timeout=30); r.raise_for_status()
    raw=pd.read_csv(io.BytesIO(r.content)); raw.columns=[str(c).strip().upper() for c in raw.columns]
    sc=next((c for c in raw.columns if c=="SYMBOL" or c.endswith("SYMBOL")),None)
    nc=next((c for c in raw.columns if "COMPANY" in c or "NAME" in c),None)
    ser=next((c for c in raw.columns if "SERIES" in c),None)
    isin=next((c for c in raw.columns if "ISIN" in c),None)
    if not sc or not nc: raise ValueError(f"Unexpected NSE file columns: {list(raw.columns)}")
    if ser: raw=raw[raw[ser].astype(str).str.upper().eq("EQ")]
    out=pd.DataFrame({"symbol":raw[sc].astype(str).str.strip(),"company":raw[nc].astype(str).str.strip(),"exchange":"NSE","sector":"Unknown"})
    if isin: out["isin"]=raw[isin].astype(str).str.strip()
    out=out[out.symbol.str.fullmatch(r"[A-Z0-9&_-]+",na=False)].drop_duplicates("symbol").sort_values("symbol")
    out["yahoo_symbol"]=out.symbol+".NS"
    CACHE.parent.mkdir(exist_ok=True); out.to_csv(CACHE,index=False)
    return out
def load_cached_nse_universe():
    return pd.read_csv(CACHE).fillna("") if CACHE.exists() else pd.DataFrame()
def combine_universe(nse,bse):
    frames=[nse] if not nse.empty else []
    if bse is not None and not bse.empty:
        req={"symbol","company","exchange","sector","yahoo_symbol"}
        if req.issubset(bse.columns):
            b=bse[bse.exchange.astype(str).str.upper().eq("BSE")]
            frames.append(b)
    return pd.concat(frames,ignore_index=True).drop_duplicates("yahoo_symbol").fillna("") if frames else pd.DataFrame()
