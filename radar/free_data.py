import pandas as pd, yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_daily_history(symbol, period="6mo"):
    df=yf.download(symbol,period=period,interval="1d",auto_adjust=True,progress=False,threads=False,timeout=18)
    if df is None or df.empty: return pd.DataFrame()
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    df=df.rename(columns=str.title)
    needed=["Open","High","Low","Close","Volume"]
    if not set(needed).issubset(df.columns): return pd.DataFrame()
    return df[needed].dropna()

def _one(row):
    sym=str(row.get("yahoo_symbol","")).strip()
    if not sym: return None
    try:
        h=fetch_daily_history(sym)
        if len(h)<35: return None
        return (dict(row),h)
    except Exception: return None

def fetch_many(universe, progress_callback=None, workers=6):
    rows=list(universe.to_dict("records")); results=[]
    if not rows: return results
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(_one,row):i for i,row in enumerate(rows)}
        done=0
        for fut in as_completed(futures):
            done+=1
            item=fut.result()
            if item is not None: results.append(item)
            if progress_callback: progress_callback(done,len(rows),len(results))
    return results

def fetch_nifty():
    try: return fetch_daily_history("^NSEI")
    except Exception: return pd.DataFrame()

def market_context(nifty):
    if nifty.empty or len(nifty)<30: return {"regime":"unknown","nifty_change_1d":None,"nifty_change_5d":None}
    c=nifty.Close
    ch1=(c.iloc[-1]/c.iloc[-2]-1)*100; ch5=(c.iloc[-1]/c.iloc[-6]-1)*100
    ema20=c.ewm(span=20).mean().iloc[-1]
    regime="bullish" if c.iloc[-1]>ema20 and ch5>0 else ("bearish" if c.iloc[-1]<ema20 and ch5<0 else "mixed")
    return {"regime":regime,"nifty_change_1d":round(ch1,2),"nifty_change_5d":round(ch5,2)}
