import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_daily_history(symbol, period="6mo"):
    """Fetch adjusted daily OHLCV; Yahoo/yfinance is unofficial and may be delayed."""
    df=yf.download(symbol,period=period,interval="1d",auto_adjust=True,progress=False,threads=False,timeout=18)
    if df is None or df.empty: return pd.DataFrame()
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    df=df.rename(columns=str.title)
    needed=["Open","High","Low","Close","Volume"]
    if not set(needed).issubset(df.columns): return pd.DataFrame()
    df=df[needed].apply(pd.to_numeric,errors="coerce").dropna()
    df=df[~df.index.duplicated(keep="last")].sort_index()
    return df[(df.Close>0)&(df.Volume>=0)]

def _one(row):
    symbol=str(row.get("yahoo_symbol","")).strip()
    if not symbol: return None
    try:
        history=fetch_daily_history(symbol)
        if len(history)<61: return None
        return (dict(row),history)
    except Exception: return None

def fetch_many(universe,progress_callback=None,workers=6):
    rows=list(universe.to_dict("records")); results=[]
    if not rows: return results
    with ThreadPoolExecutor(max_workers=max(1,min(int(workers),8))) as pool:
        futures=[pool.submit(_one,row) for row in rows]; done=0
        for future in as_completed(futures):
            done+=1
            try:
                item=future.result()
                if item is not None: results.append(item)
            except Exception: pass
            if progress_callback: progress_callback(done,len(rows),len(results))
    return results

def fetch_nifty():
    try: return fetch_daily_history("^NSEI")
    except Exception: return pd.DataFrame()

def market_context(nifty):
    empty={"regime":"unknown","nifty_change_1d":None,"nifty_change_5d":None,
           "nifty_ret20_pct":None,"nifty_ret60_pct":None,"data_date":None}
    if nifty is None or nifty.empty or len(nifty)<30: return empty
    c=nifty.Close.astype(float)
    ch1=(c.iloc[-1]/c.iloc[-2]-1)*100; ch5=(c.iloc[-1]/c.iloc[-6]-1)*100
    ret20=(c.iloc[-1]/c.iloc[-21]-1)*100
    ret60=(c.iloc[-1]/c.iloc[-61]-1)*100 if len(c)>=61 else None
    e20=c.ewm(span=20,adjust=False).mean().iloc[-1]
    e50=c.ewm(span=50,adjust=False).mean().iloc[-1]
    regime="bullish" if c.iloc[-1]>e20>e50 and ch5>0 else "bearish" if c.iloc[-1]<e20<e50 and ch5<0 else "mixed"
    return {"regime":regime,"nifty_change_1d":round(float(ch1),2),"nifty_change_5d":round(float(ch5),2),
      "nifty_ret20_pct":round(float(ret20),2),"nifty_ret60_pct":round(float(ret60),2) if ret60 is not None else None,
      "data_date":str(c.index[-1])[:10]}
