"""Evidence-first multi-timeframe stock ranking; scores are not calibrated probabilities."""
import numpy as np
import pandas as pd

def _clip(value, low=0.0, high=100.0):
    return float(max(low, min(high, value)))

def _rsi(close, period=14):
    delta=close.diff()
    gain=delta.clip(lower=0).ewm(alpha=1/period,adjust=False,min_periods=period).mean().iloc[-1]
    loss=-delta.clip(upper=0).ewm(alpha=1/period,adjust=False,min_periods=period).mean().iloc[-1]
    if not np.isfinite(gain) or not np.isfinite(loss): return 50.0
    if loss<=0: return 100.0 if gain>0 else 50.0
    return float(100-100/(1+gain/loss))

def _atr(frame,period=14):
    prev=frame.Close.shift(1)
    tr=pd.concat([frame.High-frame.Low,(frame.High-prev).abs(),(frame.Low-prev).abs()],axis=1).max(axis=1)
    return float(tr.ewm(alpha=1/period,adjust=False,min_periods=period).mean().iloc[-1])

def _adx(frame,period=14):
    up,down=frame.High.diff(),-frame.Low.diff()
    plus=up.where((up>down)&(up>0),0.0)
    minus=down.where((down>up)&(down>0),0.0)
    prev=frame.Close.shift(1)
    tr=pd.concat([frame.High-frame.Low,(frame.High-prev).abs(),(frame.Low-prev).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/period,adjust=False,min_periods=period).mean()
    pdi=100*plus.ewm(alpha=1/period,adjust=False,min_periods=period).mean()/atr.replace(0,np.nan)
    mdi=100*minus.ewm(alpha=1/period,adjust=False,min_periods=period).mean()/atr.replace(0,np.nan)
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    value=dx.ewm(alpha=1/period,adjust=False,min_periods=period).mean().iloc[-1]
    return float(value) if np.isfinite(value) else np.nan

def apply_news_overlay(base_score,headlines):
    """Freshness/source/confidence-weighted headline adjustment capped at +/-5."""
    weighted,flags=[],[]
    for item in headlines or []:
        try:
            sentiment=float(item.get("sentiment",0))
            confidence=float(item.get("sentiment_confidence",0))
            source_weight=float(item.get("source_weight",0.5))
            age=item.get("age_hours")
            # Undated stories may be displayed for context but must not move
            # the score: their freshness cannot be verified.
            freshness=0.0 if age is None else max(0.15,1-max(0.0,float(age))/120)
            weight=max(0.0,confidence*source_weight*freshness)
            if weight: weighted.append((sentiment,weight))
            if item.get("source_type") in ("exchange","regulator") and sentiment<=-0.5 and confidence>=0.5:
                flags.append(f"Negative {item.get('source','official')} headline")
        except (TypeError,ValueError):
            continue
    if not weighted: return round(float(base_score),1),None,0.0,sorted(set(flags))
    total=sum(w for _,w in weighted)
    average=sum(s*w for s,w in weighted)/total
    news_score=_clip(50+average*50)
    adjustment=max(-5.0,min(5.0,average*5.0))
    return round(_clip(base_score+adjustment),1),round(news_score,1),round(adjustment,2),sorted(set(flags))

def score_stock(meta,history,market=None):
    market=market or {}
    required=["Open","High","Low","Close","Volume"]
    if history is None or history.empty or not set(required).issubset(history.columns):
        raise ValueError("Missing OHLCV data")
    h=history[required].apply(pd.to_numeric,errors="coerce").dropna().sort_index()
    h=h[~h.index.duplicated(keep="last")]
    h=h[(h.Close>0)&(h.Volume>=0)]
    if len(h)<61: raise ValueError("At least 61 daily bars required")
    c,v=h.Close.astype(float),h.Volume.astype(float)
    last,prev=float(c.iloc[-1]),float(c.iloc[-2])
    def ret(n):
        return (last/float(c.iloc[-n-1])-1)*100 if len(c)>n else None
    r1,r5,r20,r60,r120=ret(1),ret(5),ret(20),ret(60),ret(120)
    ema20s,ema50s=c.ewm(span=20,adjust=False).mean(),c.ewm(span=50,adjust=False).mean()
    ema200s=c.ewm(span=200,adjust=False).mean() if len(c)>=200 else None
    e20,e50=float(ema20s.iloc[-1]),float(ema50s.iloc[-1])
    e200=float(ema200s.iloc[-1]) if ema200s is not None else None
    slope20=float((ema20s.iloc[-1]/ema20s.iloc[-6]-1)*100)
    if e200 is not None:
        trend=100 if last>e20>e50>e200 and slope20>0.2 else 90 if last>e20>e50>e200 else 76 if last>e50>e200 else 60 if last>e200 else 35 if last>e50 else 18
        long_term=95 if last>e200 and e50>e200 else 65 if last>e200 else 20
    else:
        trend=90 if last>e20>e50 and slope20>0 else 68 if last>e50 else 35
        long_term=None
    macd=c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean()
    macd_hist_pct=float((macd.iloc[-1]-macd.ewm(span=9,adjust=False).mean().iloc[-1])/last*100)
    macd_score=_clip(50+macd_hist_pct*18)
    rsi=_rsi(c)
    rsi_score=95 if 52<=rsi<=67 else 78 if 45<=rsi<52 or 67<rsi<=72 else 55 if 40<=rsi<45 or 72<rsi<=78 else 28 if 35<=rsi<40 or 78<rsi<=83 else 12
    atr=_atr(h)
    atr_pct=atr/last*100 if np.isfinite(atr) else np.nan
    adx=_adx(h)
    if np.isfinite(adx) and adx>=25: trend=min(100,trend+5)
    vol_score=92 if np.isfinite(atr_pct) and atr_pct<=2.5 else 78 if np.isfinite(atr_pct) and atr_pct<=4 else 58 if np.isfinite(atr_pct) and atr_pct<=5.5 else 32 if np.isfinite(atr_pct) and atr_pct<=8 else 15 if np.isfinite(atr_pct) else 40
    median_volume=float(v.iloc[-21:-1].median())
    rvol=float(v.iloc[-1]/median_volume) if median_volume>0 else np.nan
    volume_score=20 if not np.isfinite(rvol) or rvol<.5 else 40 if rvol<.8 else 60 if rvol<1.2 else 88 if rvol<=2.5 else 68 if rvol<=4 else 35
    turnover=float((c*v).tail(20).median())
    liquidity=10 if turnover<5e6 else 30 if turnover<1e7 else 50 if turnover<2.5e7 else 70 if turnover<1e8 else 85 if turnover<5e8 else 100
    n20,n60,n120=market.get("nifty_ret20_pct"),market.get("nifty_ret60_pct"),market.get("nifty_ret120_pct")
    rs=None
    if n20 is not None and r20 is not None:
        rs20=r20-float(n20)
        rs60=r60-float(n60) if n60 is not None and r60 is not None else rs20
        rs120=r120-float(n120) if n120 is not None and r120 is not None else rs60
        rs=.5*rs20+.3*rs60+.2*rs120
        rs_score=_clip(50+rs*2.5)
    else: rs_score=None
    momentum_items=[(r5,.15),(r20,.4),(r60,.3),(r120,.15)]
    momentum_items=[(x,w) for x,w in momentum_items if x is not None]
    momentum=_clip(50+sum(x*w for x,w in momentum_items)*1.8)
    high55=float(c.tail(min(55,len(c))).max())
    distance_high=(last/high55-1)*100 if high55 else 0
    breakout=90 if distance_high>=-2 else 75 if distance_high>=-5 else 55 if distance_high>=-10 else 30
    regime=str(market.get("regime","unknown")).lower()
    global_risk=str(market.get("global_risk","unknown")).lower()
    market_score={"bullish":90,"mixed":55,"bearish":15}.get(regime,45)
    if global_risk=="risk_off": market_score=max(10,market_score-12)
    elif global_risk=="risk_on": market_score=min(100,market_score+5)
    parts={"trend_score":trend,"long_term_score":long_term,"momentum_score":momentum,
      "relative_strength_score":rs_score,"macd_score":macd_score,"breakout_score":breakout,
      "volume_score":volume_score,"rsi_score":rsi_score,"liquidity_score":liquidity,
      "volatility_score":vol_score,"market_score":market_score}
    weights={"trend_score":15,"long_term_score":10,"momentum_score":14,"relative_strength_score":14,
      "macd_score":8,"breakout_score":8,"volume_score":7,"rsi_score":7,"liquidity_score":7,
      "volatility_score":5,"market_score":5}
    weight_sum=sum(weights[k] for k,x in parts.items() if x is not None)
    base=sum(weights[k]*x for k,x in parts.items() if x is not None)/weight_sum
    gap=(float(h.Open.iloc[-1])/prev-1)*100
    date=pd.Timestamp(h.index[-1])
    if date.tzinfo is not None: date=date.tz_convert("Asia/Kolkata").tz_localize(None)
    age=max(0,(pd.Timestamp.now(tz="Asia/Kolkata").date()-date.date()).days)
    flags=[]
    if turnover<1e7: flags.append("Low liquidity: median traded value below ₹1 crore/day")
    if np.isfinite(rvol) and rvol>6: flags.append("Unusual volume spike: verify official filing")
    if abs(gap)>6: flags.append("Large one-day gap: avoid chasing")
    if rsi>78: flags.append("RSI above 78: extended / overbought")
    if np.isfinite(atr_pct) and atr_pct>5.5: flags.append("High ATR volatility: reduce position size")
    if e200 is None: flags.append("EMA200 unavailable: fewer than 200 bars")
    if age>2: flags.append(f"Price data is {age} calendar days old")
    if regime=="bearish": flags.append("Nifty regime bearish")
    if global_risk=="risk_off": flags.append("Global market context is risk-off")
    stale=age>5
    liquid=turnover>=1e7
    event_spike=abs(gap)>8 and np.isfinite(rvol) and rvol>6
    eligible=bool(not stale and liquid and not event_spike)
    if stale: setup="Reject — stale data"
    elif not liquid: setup="Reject — low liquidity"
    elif event_spike: setup="Wait — event gap / volume spike"
    elif regime=="bearish": setup="Wait — bearish market"
    elif base>=72 and trend>=65 and (rs_score is None or rs_score>=50) and rsi<=78: setup="Watchlist candidate"
    else: setup="Wait — confirmation needed"
    risk="High" if not eligible or rsi>78 or (np.isfinite(atr_pct) and atr_pct>5.5) or (np.isfinite(rvol) and rvol>6) or regime=="bearish" or global_risk=="risk_off" else "Moderate" if (np.isfinite(atr_pct) and atr_pct>3.5) or rsi>72 else "Controlled"
    entry_low,entry_high=last-.15*atr,last+.15*atr
    stop=max(.01,last-1.5*atr)
    target1,target2=last+2*atr,last+3*atr
    reasons=[
      f"Trend: close ₹{last:.2f}; EMA20 ₹{e20:.2f}; EMA50 ₹{e50:.2f}; "+(f"EMA200 ₹{e200:.2f}" if e200 is not None else "EMA200 unavailable"),
      f"Momentum: 5D {r5:+.2f}%; 20D {r20:+.2f}%; "+(f"60D {r60:+.2f}%" if r60 is not None else "60D unavailable"),
      f"Relative strength vs Nifty: {rs:+.2f} percentage points" if rs is not None else "Relative strength vs Nifty unavailable",
      f"MACD histogram {macd_hist_pct:+.3f}% of price; ADX {adx:.1f}" if np.isfinite(adx) else f"MACD histogram {macd_hist_pct:+.3f}% of price; ADX unavailable",
      f"Relative volume: {rvol:.2f}x (prior 20-session median)" if np.isfinite(rvol) else "Relative volume unavailable",
      f"RSI(14): {rsi:.1f}; ATR(14): {atr_pct:.2f}%" if np.isfinite(atr_pct) else f"RSI(14): {rsi:.1f}; ATR unavailable",
      f"Median 20D traded value: ₹{turnover:,.0f}",
      f"Nifty regime: {regime}; global context: {global_risk}; data age: {age} calendar days"]
    return {"price":round(last,2),"change_1d_pct":round(r1,2),"ret5_pct":round(r5,2) if r5 is not None else np.nan,
      "ret20_pct":round(r20,2) if r20 is not None else np.nan,"ret60_pct":round(r60,2) if r60 is not None else np.nan,
      "ret120_pct":round(r120,2) if r120 is not None else np.nan,"relative_strength_pct":round(rs,2) if rs is not None else np.nan,
      "distance_55d_high_pct":round(distance_high,2),"rvol":round(rvol,2) if np.isfinite(rvol) else np.nan,
      "rsi":round(rsi,1),"adx":round(adx,1) if np.isfinite(adx) else np.nan,
      "atr_pct":round(atr_pct,2) if np.isfinite(atr_pct) else np.nan,"turnover20":round(turnover,0),"gap_pct":round(gap,2),
      "score":round(_clip(base),1),"base_score":round(_clip(base),1),"risk":risk,"eligible":eligible,
      "setup_status":setup,"entry_low":round(entry_low,2),"entry_high":round(entry_high,2),"stop_loss":round(stop,2),
      "target1":round(target1,2),"target2":round(target2,2),"age_days":age,"data_date":str(date.date()),
      **{k:round(float(x),1) if x is not None else None for k,x in parts.items()},
      "news_score":None,"news_adjustment":0.0,"news_flags":[],"reasons":reasons,"flags":flags,"news":[]}
