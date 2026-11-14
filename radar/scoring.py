"""Transparent daily-swing ranking; scores are heuristics, not calibrated probabilities."""
import numpy as np
import pandas as pd

def _clip(x, lo=0.0, hi=100.0):
    return float(max(lo, min(hi, x)))

def _rsi(c, n=14):
    d=c.diff()
    g=d.clip(lower=0).rolling(n).mean().iloc[-1]
    l=-d.clip(upper=0).rolling(n).mean().iloc[-1]
    if not np.isfinite(g) or not np.isfinite(l): return 50.0
    if l <= 0: return 100.0 if g > 0 else 50.0
    return float(100 - 100/(1 + g/l))

def _atr(h, n=14):
    prev=h.Close.shift(1)
    tr=pd.concat([h.High-h.Low,(h.High-prev).abs(),(h.Low-prev).abs()],axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])

def apply_news_overlay(base_score, headlines):
    """Keyword sentiment can move ranking by at most +/-4 points."""
    vals=[float(x.get("sentiment",0)) for x in (headlines or []) if x.get("sentiment") is not None]
    if not vals: return round(float(base_score),1), None, 0.0
    news_score=_clip(50+float(np.mean(vals))*50)
    adj=max(-4.0,min(4.0,(news_score-50)*0.08))
    return round(_clip(base_score+adj),1), round(news_score,1), round(adj,2)

def score_stock(meta, h, market=None):
    market=market or {}
    required=["Open","High","Low","Close","Volume"]
    if h is None or h.empty or not set(required).issubset(h.columns):
        raise ValueError("Missing OHLCV data")
    h=h[required].apply(pd.to_numeric,errors="coerce").dropna().sort_index()
    h=h[~h.index.duplicated(keep="last")]
    if len(h)<61: raise ValueError("At least 61 daily bars required")
    c,v=h.Close.astype(float),h.Volume.astype(float)
    last,prev=float(c.iloc[-1]),float(c.iloc[-2])
    if last<=0 or prev<=0: raise ValueError("Invalid close")
    ret1=(last/prev-1)*100
    ret5=(last/float(c.iloc[-6])-1)*100
    ret20=(last/float(c.iloc[-21])-1)*100
    ret60=(last/float(c.iloc[-61])-1)*100
    e20s=c.ewm(span=20,adjust=False).mean()
    e50s=c.ewm(span=50,adjust=False).mean()
    e20,e50=float(e20s.iloc[-1]),float(e50s.iloc[-1])
    slope=float(e20s.iloc[-1]/e20s.iloc[-6]-1)*100
    trend=100 if last>e20>e50 and slope>0 else 90 if last>e20>e50 else 75 if last>e50 and e20>e50 else 62 if last>e20 else 20 if last<e20<e50 else 38
    momentum=_clip(50+ret5*1.3+ret20*1.35+ret60*.35)
    n20,n60=market.get("nifty_ret20_pct"),market.get("nifty_ret60_pct")
    if n20 is not None:
        rs=ret20-float(n20)
        if n60 is not None: rs=.65*rs+.35*(ret60-float(n60))
        rs_score=_clip(50+rs*3)
    else: rs,rs_score=None,None
    median_vol=float(v.iloc[-21:-1].median())
    rvol=float(v.iloc[-1]/median_vol) if median_vol>0 else np.nan
    volume=45 if not np.isfinite(rvol) else 20 if rvol<.5 else 35 if rvol<.8 else 52 if rvol<1.2 else 82 if rvol<=2.5 else 68 if rvol<=4 else 42
    rsi=_rsi(c)
    rsi_score=88 if 52<=rsi<=68 else 70 if 45<=rsi<52 or 68<rsi<=73 else 48 if 40<=rsi<45 or 73<rsi<=78 else 22
    turnover=float((c*v).tail(20).median())
    liquidity=10 if turnover<5e6 else 30 if turnover<1e7 else 50 if turnover<2.5e7 else 70 if turnover<1e8 else 85 if turnover<5e8 else 100
    atr=_atr(h); atr_pct=atr/last*100 if np.isfinite(atr) else np.nan
    volatility=35 if not np.isfinite(atr_pct) else 92 if atr_pct<=2.5 else 75 if atr_pct<=4 else 55 if atr_pct<=5.5 else 32 if atr_pct<=8 else 15
    regime=str(market.get("regime","unknown")).lower()
    market_score={"bullish":90,"mixed":55,"bearish":20}.get(regime,50)
    components={"trend_score":trend,"momentum_score":momentum,"relative_strength_score":rs_score,
        "volume_score":volume,"rsi_score":rsi_score,"liquidity_score":liquidity,
        "volatility_score":volatility,"market_score":market_score}
    weights={"trend_score":22,"momentum_score":18,"relative_strength_score":15,
        "volume_score":10,"rsi_score":10,"liquidity_score":10,"volatility_score":10,"market_score":5}
    weight_sum=sum(weights[k] for k,x in components.items() if x is not None)
    base=sum(weights[k]*x for k,x in components.items() if x is not None)/weight_sum
    gap=(float(h.Open.iloc[-1])/prev-1)*100
    date=pd.Timestamp(h.index[-1])
    if date.tzinfo is not None: date=date.tz_convert("Asia/Kolkata").tz_localize(None)
    age=max(0,(pd.Timestamp.now(tz="Asia/Kolkata").date()-date.date()).days)
    flags=[]
    if turnover<1e7: flags.append("Low liquidity: median traded value below ₹1 crore/day")
    if np.isfinite(rvol) and rvol>6: flags.append("Unusual volume spike: verify exchange filing/news")
    if abs(gap)>6: flags.append("Large one-day gap: avoid chasing; verify catalyst")
    if rsi>78: flags.append("RSI above 78: extended / overbought")
    if np.isfinite(atr_pct) and atr_pct>5.5: flags.append("High ATR volatility: reduce position size")
    if age>2: flags.append(f"Price data is {age} calendar days old")
    if regime=="bearish": flags.append("Nifty regime bearish: long setups need extra confirmation")
    stale=age>5; liquid=turnover>=1e7; event_spike=abs(gap)>8 and np.isfinite(rvol) and rvol>6
    eligible=bool(not stale and liquid and not event_spike)
    if stale: setup="Reject — stale data"
    elif not liquid: setup="Reject — low liquidity"
    elif event_spike: setup="Wait — event gap / volume spike"
    elif regime=="bearish": setup="Wait — bearish market"
    elif base>=70 and trend>=70 and rsi<=78: setup="Watchlist candidate"
    else: setup="Wait — confirmation needed"
    risk="High" if not eligible or rsi>78 or (np.isfinite(atr_pct) and atr_pct>5.5) or (np.isfinite(rvol) and rvol>6) or regime=="bearish" else "Moderate" if (np.isfinite(atr_pct) and atr_pct>3.5) or rsi>72 else "Controlled"
    # Close-based educational levels, never live execution prices.
    entry_low=last-.15*atr; entry_high=last+.15*atr
    stop=max(.01,last-1.5*atr); target1=last+2*atr; target2=last+3*atr
    reasons=[
      f"Trend: close ₹{last:.2f}; EMA20 ₹{e20:.2f}; EMA50 ₹{e50:.2f}; EMA20 slope {slope:+.2f}%",
      f"Momentum: 5D {ret5:+.2f}%; 20D {ret20:+.2f}%; 60D {ret60:+.2f}%",
      f"Relative strength vs Nifty: {rs:+.2f} percentage points" if rs is not None else "Relative strength vs Nifty unavailable",
      f"Relative volume: {rvol:.2f}x (median of prior 20 sessions)" if np.isfinite(rvol) else "Relative volume unavailable",
      f"RSI(14): {rsi:.1f}; ATR(14): {atr_pct:.2f}%" if np.isfinite(atr_pct) else f"RSI(14): {rsi:.1f}; ATR unavailable",
      f"Median 20D traded value: ₹{turnover:,.0f}",f"Nifty regime: {regime}; price-data age: {age} calendar days"]
    return {"price":round(last,2),"change_1d_pct":round(ret1,2),"ret5_pct":round(ret5,2),
      "ret20_pct":round(ret20,2),"ret60_pct":round(ret60,2),"rvol":round(rvol,2) if np.isfinite(rvol) else np.nan,
      "rsi":round(rsi,1),"atr_pct":round(atr_pct,2) if np.isfinite(atr_pct) else np.nan,
      "turnover20":round(turnover,0),"gap_pct":round(gap,2),"score":round(_clip(base),1),
      "base_score":round(_clip(base),1),"risk":risk,"eligible":eligible,"setup_status":setup,
      "entry_low":round(entry_low,2),"entry_high":round(entry_high,2),"stop_loss":round(stop,2),
      "target1":round(target1,2),"target2":round(target2,2),"age_days":age,"data_date":str(date.date()),
      **{k:round(float(x),1) if x is not None else None for k,x in components.items()},
      "news_score":None,"news_adjustment":0.0,"reasons":reasons,"flags":flags,"news":[]}
