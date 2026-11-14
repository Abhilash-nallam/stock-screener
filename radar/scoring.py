import numpy as np
def score_stock(meta,h):
    c=h.Close.astype(float); v=h.Volume.astype(float); last=float(c.iloc[-1])
    ret1=(last/float(c.iloc[-2])-1)*100; ret5=(last/float(c.iloc[-6])-1)*100
    ret20=(last/float(c.iloc[-21])-1)*100 if len(c)>=21 else 0
    ema20=float(c.ewm(span=20).mean().iloc[-1]); ema50=float(c.ewm(span=50).mean().iloc[-1])
    trend=100 if last>ema20>ema50 else 75 if last>ema20 else 30 if last<ema20<ema50 else 50
    avgvol=float(v.iloc[-21:-1].mean()) if len(v)>=21 else 0
    rvol=float(v.iloc[-1]/avgvol) if avgvol>0 else np.nan
    volume_score=max(0,min(100,50+(rvol-1)*25)) if np.isfinite(rvol) else 50
    momentum=max(0,min(100,50+ret5*5+ret20*1.5))
    delta=c.diff(); gain=delta.clip(lower=0).rolling(14).mean().iloc[-1]; loss=-delta.clip(upper=0).rolling(14).mean().iloc[-1]
    rs=float(gain/loss) if loss and np.isfinite(loss) else 99
    rsi=100-100/(1+rs)
    rsi_score=80 if 50<=rsi<=68 else 55 if 40<=rsi<50 or 68<rsi<=75 else 25 if rsi>80 or rsi<35 else 45
    # Neutral placeholder until post-ranking news lookup is applied.
    news_score=50.0
    score=.35*trend+.30*momentum+.20*volume_score+.15*rsi_score
    risk="High" if rsi>75 or (np.isfinite(rvol) and rvol>4) else "Moderate" if score>=60 else "High"
    reasons=[f"Trend structure: {'above EMA20 and EMA50' if last>ema20>ema50 else 'mixed / below trend'}",
             f"5-day return: {ret5:+.2f}%; 20-day return: {ret20:+.2f}%",
             f"Relative volume: {rvol:.2f}x" if np.isfinite(rvol) else "Relative volume unavailable",
             f"RSI(14): {rsi:.1f}","News not yet scored; headlines are fetched only for leading technical candidates"]
    return {"price":last,"change_1d_pct":ret1,"ret5_pct":ret5,"ret20_pct":ret20,
            "rvol":rvol,"rsi":rsi,"score":round(score,1),"risk":risk,
            "trend_score":round(trend,1),"momentum_score":round(momentum,1),
            "volume_score":round(volume_score,1),"rsi_score":round(rsi_score,1),
            "news_score":news_score,"reasons":reasons,"news":[]}
