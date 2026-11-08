"""Technical indicators computed with pandas and numpy."""
import pandas as pd
import numpy as np

def rsi(series, period=14):
    delta=series.diff()
    gain,loss=delta.clip(lower=0),-delta.clip(upper=0)
    avg_gain,avg_loss=gain.rolling(period).mean(),loss.rolling(period).mean()
    rs=avg_gain/avg_loss.replace(0,np.nan)
    return 100-(100/(1+rs))

def moving_averages(df):
    return {"ma20":df["Close"].rolling(20).mean().iloc[-1] if len(df)>=20 else None,
            "ma50":df["Close"].rolling(50).mean().iloc[-1] if len(df)>=50 else None,
            "ma200":df["Close"].rolling(200).mean().iloc[-1] if len(df)>=200 else None}

def volume_spike(df,lookback=20):
    if len(df)<lookback+1:return None
    avg=df["Volume"].iloc[-(lookback+1):-1].mean()
    return df["Volume"].iloc[-1]/avg if avg else None

def relative_strength(stock_df,nifty_df,days=20):
    if len(stock_df)<days or len(nifty_df)<days:return None
    stock_ret=stock_df["Close"].iloc[-1]/stock_df["Close"].iloc[-days]-1
    nifty_ret=nifty_df["Close"].iloc[-1]/nifty_df["Close"].iloc[-days]-1
    if nifty_ret==0:return None
    return stock_ret/nifty_ret if nifty_ret>0 else 1+(stock_ret-nifty_ret)

def analyze(df,nifty_df=None):
    if df is None or df.empty or len(df)<20:return None
    close=df["Close"]; price=close.iloc[-1]
    rs=rsi(close); current_rsi=rs.iloc[-1] if not rs.empty else None
    mas=moving_averages(df); vol=volume_spike(df)
    rel=relative_strength(df,nifty_df) if nifty_df is not None else None
    trend="neutral"
    if mas["ma50"] and mas["ma200"]:
        if price>mas["ma50"]>mas["ma200"]:trend="strong_uptrend"
        elif price>mas["ma50"]:trend="uptrend"
        elif price<mas["ma50"]<mas["ma200"]:trend="downtrend"
    support=close.rolling(50).min().iloc[-1] if len(close)>=50 else close.min()
    resistance=close.rolling(50).max().iloc[-1] if len(close)>=50 else close.max()
    return {"current_price":round(price,2),
      "rsi":round(current_rsi,1) if current_rsi is not None and not np.isnan(current_rsi) else None,
      "ma20":round(mas["ma20"],2) if mas["ma20"] else None,
      "ma50":round(mas["ma50"],2) if mas["ma50"] else None,
      "ma200":round(mas["ma200"],2) if mas["ma200"] else None,
      "trend":trend,"volume_spike_ratio":round(vol,2) if vol else None,
      "relative_strength_vs_nifty":round(rel,2) if rel else None,
      "support":round(support,2),"resistance":round(resistance,2)}
