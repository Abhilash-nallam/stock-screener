"""Daily screening pipeline."""
import os,json
from datetime import datetime
from config import TOP_N,REPORT_DIR,MIN_MARKET_CAP_CR
import data_sources as ds
import technical_analysis as ta
import scoring,report as rpt,notifier
def run():
    os.makedirs(REPORT_DIR,exist_ok=True)
    print("[1/4] Fetching top gainers...")
    gainers=ds.get_top_gainers(limit=50)
    if gainers.empty:
        print("[warn] Top gainers unavailable — fallback universe")
        candidates=ds.get_universe_symbols();pct_changes={}
    else:
        symbol_col="symbol" if "symbol" in gainers.columns else gainers.columns[0]
        change_col=next((c for c in gainers.columns if "change" in c.lower()),None)
        candidates=gainers[symbol_col].tolist()
        pct_changes=dict(zip(gainers[symbol_col],gainers[change_col])) if change_col else {}
    print(f"[2/4] Screening {len(candidates)} candidates...")
    nifty=ds.get_nifty_history(period="6mo");results=[]
    for symbol in candidates:
        try:
            fund=ds.get_fundamentals(symbol);ds.throttle()
            cap=fund.get("market_cap") or 0
            if cap and cap<MIN_MARKET_CAP_CR*1_00_00_000:continue
            hist=ds.get_price_history(symbol,period="6mo");ds.throttle()
            tech=ta.analyze(hist,nifty)
            if tech is None:continue
            scored=scoring.compute_score(symbol,fund,tech,pct_changes.get(symbol))
            scored["tech"]=tech;scored["fund"]=fund;results.append(scored)
        except Exception as e:print(f"[warn] skipped {symbol}: {e}")
    print(f"[3/4] Ranking {len(results)} screened stocks...")
    ranked=sorted(results,key=lambda r:r["total_score"],reverse=True)[:TOP_N]
    ranked=[r for r in ranked if r["total_score"]>=50]
    print("[4/4] Building report and sending alerts...")
    as_of=datetime.now().strftime("%Y-%m-%d %H:%M IST")
    md=rpt.build_markdown_report(ranked,as_of);tg=rpt.build_telegram_message(ranked,as_of)
    date_str=datetime.now().strftime("%Y-%m-%d")
    with open(os.path.join(REPORT_DIR,f"report_{date_str}.md"),"w") as f:f.write(md)
    with open(os.path.join(REPORT_DIR,"latest.json"),"w") as f:json.dump({"as_of":as_of,"results":ranked},f,default=str,indent=2)
    notifier.send_telegram(tg);notifier.send_email(f"Stock Screen {date_str}",md)
    print(f"Done. Report saved for {date_str}")
    return ranked
if __name__=="__main__":run()
