"""Fundamental, valuation, technical, momentum and risk scoring."""
from config import MIN_ROE,MAX_DEBT_TO_EQUITY,RSI_OVERBOUGHT,RSI_OVERSOLD
def score_fundamental(fund):
    if not fund or fund.get("roe") is None:return 0,["No fundamental data available"]
    points,notes=0,[];roe=(fund.get("roe") or 0)*100
    if roe>=MIN_ROE:points+=10;notes.append(f"ROE {roe:.1f}% (healthy)")
    else:notes.append(f"ROE {roe:.1f}% (below {MIN_ROE}% threshold)")
    de=fund.get("debt_to_equity")
    if de is not None:
        ratio=de/100 if de>10 else de
        if ratio<=MAX_DEBT_TO_EQUITY:points+=8;notes.append(f"D/E {ratio:.2f} (manageable)")
        else:notes.append(f"D/E {ratio:.2f} (high leverage)")
    growth=fund.get("revenue_growth")
    if growth is not None and growth>0:points+=7;notes.append(f"Revenue growth {growth*100:.1f}%")
    return points,notes
def score_valuation(fund):
    pe=fund.get("pe_ratio") if fund else None
    if pe is None or pe<=0:return 0,["P/E unavailable"]
    if pe<15:return 20,[f"P/E {pe:.1f} (cheap)"]
    if pe<30:return 12,[f"P/E {pe:.1f} (fair)"]
    return 4,[f"P/E {pe:.1f} (expensive — verify growth justifies it)"]
def score_technical(tech):
    if not tech:return 0,["No technical data"]
    points,notes=0,[];rsi=tech.get("rsi")
    if rsi is not None:
        if RSI_OVERSOLD<rsi<RSI_OVERBOUGHT:points+=10;notes.append(f"RSI {rsi} (healthy range)")
        elif rsi>=RSI_OVERBOUGHT:notes.append(f"RSI {rsi} (overbought — pullback risk)")
        else:notes.append(f"RSI {rsi} (oversold — could bounce or fall)")
    if tech.get("trend")=="strong_uptrend":points+=10;notes.append("Price above both 50 & 200 DMA")
    elif tech.get("trend")=="uptrend":points+=6;notes.append("Price above 50 DMA")
    elif tech.get("trend")=="downtrend":notes.append("Downtrend — price below key averages")
    vol=tech.get("volume_spike_ratio")
    if vol and vol>1.5:points+=5;notes.append(f"Volume {vol}x average")
    return points,notes
def score_momentum(tech,pct_change_today):
    points,notes=0,[]
    if pct_change_today is not None:
        capped=min(pct_change_today,10);points+=round((capped/10)*8);notes.append(f"Today's move: {pct_change_today:.1f}%")
    rel=tech.get("relative_strength_vs_nifty") if tech else None
    if rel is not None and rel>1:points+=7;notes.append(f"Outperforming Nifty ({rel:.2f}x)")
    return points,notes
def score_risk(fund,tech):
    points,notes=15,[]
    de=fund.get("debt_to_equity") if fund else None
    if de is not None and (de/100 if de>10 else de)>MAX_DEBT_TO_EQUITY:points-=6;notes.append("High debt load increases downside risk")
    rsi=tech.get("rsi") if tech else None
    if rsi and rsi>=RSI_OVERBOUGHT:points-=5;notes.append("Overbought RSI — entry risk")
    cap=fund.get("market_cap") if fund else None
    if cap and cap<5_000_000_000:points-=4;notes.append("Smaller market cap — higher volatility/liquidity risk")
    return max(points,0),notes
def compute_score(symbol,fund,tech,pct_change_today):
    f,fn=score_fundamental(fund);v,vn=score_valuation(fund);t,tn=score_technical(tech);m,mn=score_momentum(tech,pct_change_today);r,rn=score_risk(fund,tech)
    return {"symbol":symbol,"total_score":round(f+v+t+m+r,1),"breakdown":{
      "fundamental":{"points":f,"notes":fn},"valuation":{"points":v,"notes":vn},
      "technical":{"points":t,"notes":tn},"momentum":{"points":m,"notes":mn},"risk":{"points":r,"notes":rn}}}
