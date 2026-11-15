"""CSV journal for prospective daily pick performance."""
from pathlib import Path
import pandas as pd

LEDGER_PATH=Path("data/recommendation_ledger.csv")
COLUMNS=["asof_date","symbol","company","exchange","price","score","risk","setup_status",
 "entry_low","entry_high","stop_loss","target1","target2","data_date","market_regime",
 "return_5d_pct","return_20d_pct","actual_5d_date","actual_20d_date",
 "live_price","live_score","live_entry_low","live_entry_high","live_stop","live_target1","live_target2"]

def read_ledger(path=LEDGER_PATH):
    path=Path(path)
    if not path.exists(): return pd.DataFrame(columns=COLUMNS)
    try: return pd.read_csv(path)
    except Exception: return pd.DataFrame(columns=COLUMNS)

def _refresh(ledger,histories):
    if ledger.empty: return ledger
    for idx,row in ledger.iterrows():
        exchange = str(row.get("exchange", "")).upper()
        symbol = str(row.get("symbol", ""))
        h=(histories or {}).get(f"{exchange}:{symbol}") or (histories or {}).get(symbol)
        if h is None or h.empty: continue
        dates=pd.DatetimeIndex(pd.to_datetime(h.index))
        if dates.tz is not None: dates=dates.tz_convert("Asia/Kolkata").tz_localize(None)
        forecast=pd.Timestamp(row["asof_date"]).normalize()
        pos=dates.normalize().searchsorted(forecast,side="left")
        entry=float(row.get("price",0) or 0)
        if pos>=len(dates) or entry<=0: continue
        closes=pd.to_numeric(h.Close,errors="coerce").to_numpy()
        for horizon,ret_col,date_col in [(5,"return_5d_pct","actual_5d_date"),(20,"return_20d_pct","actual_20d_date")]:
            target=pos+horizon
            if target<len(dates) and pd.notna(closes[target]):
                ledger.at[idx,ret_col]=round((float(closes[target])/entry-1)*100,2)
                ledger.at[idx,date_col]=str(dates[target].date())
    return ledger

def save_daily_picks(picks,histories,market_regime,path=LEDGER_PATH):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    ledger=_refresh(read_ledger(path),histories)
    if picks is not None and not picks.empty:
        rows=[]
        for _,r in picks.iterrows():
            rows.append({"asof_date":str(r.get("data_date") or picks["data_date"].iloc[0]),"symbol":r.get("symbol"),"company":r.get("company"),
              "exchange":r.get("exchange"),"price":r.get("price"),"score":r.get("score"),
              "risk":r.get("risk"),"setup_status":r.get("setup_status"),"entry_low":r.get("entry_low"),
              "entry_high":r.get("entry_high"),"stop_loss":r.get("stop_loss"),"target1":r.get("target1"),
              "target2":r.get("target2"),"data_date":r.get("data_date"),"market_regime":market_regime,
              "live_price":r.get("live_price"),"live_score":r.get("live_score"),
              "live_entry_low":r.get("live_entry_low"),"live_entry_high":r.get("live_entry_high"),
              "live_stop":r.get("live_stop"),"live_target1":r.get("live_target1"),"live_target2":r.get("live_target2"),
              "return_5d_pct":None,"return_20d_pct":None,"actual_5d_date":None,"actual_20d_date":None})
        ledger=pd.concat([ledger,pd.DataFrame(rows)],ignore_index=True)
        ledger=ledger.drop_duplicates(["asof_date","symbol"],keep="last")
        ledger=_refresh(ledger,histories)
    for col in COLUMNS:
        if col not in ledger.columns: ledger[col]=None
    ledger[COLUMNS].to_csv(path,index=False)
    return ledger[COLUMNS]
