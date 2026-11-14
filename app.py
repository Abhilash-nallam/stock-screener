import os, pandas as pd, streamlit as st
from dotenv import load_dotenv
from radar.free_data import fetch_many,fetch_nifty,market_context
from radar.scoring import score_stock
from radar.telegram import send_telegram
from radar.brokers import fetch_broker_accounts
from radar.universe import fetch_nse_universe, load_cached_nse_universe, combine_universe
load_dotenv()
st.set_page_config(page_title="India Stock Radar",page_icon="📡",layout="wide")
st.title("📡 India Stock Radar — Free Data Edition")
st.caption("NSE/BSE research shortlist · Daily candles + public headlines · No paid market-data API configured")
with st.sidebar:
    st.header("Scan settings")
    st.caption("Automatic NSE equity universe + optional BSE list")
    if st.button("Refresh official NSE equity list"):
        try:
            st.session_state["nse_universe"]=fetch_nse_universe()
            st.success(f"Loaded {len(st.session_state['nse_universe'])} NSE EQ symbols")
        except Exception as e:
            cached=load_cached_nse_universe()
            if not cached.empty:
                st.session_state["nse_universe"]=cached
                st.warning(f"NSE refresh failed; using cached list ({len(cached)} symbols): {e}")
            else: st.error(f"NSE download failed: {e}")
    bse_up=st.file_uploader("Optional BSE mapped CSV",type=["csv"],key="bse_file")
    min_score=st.slider("Minimum radar score",0,100,55)
    max_news=st.slider("Headlines per stock",3,10,6)
    max_symbols=st.selectbox("Maximum symbols per scan",["250","500","1000","All"],index=1)
    st.caption("For BSE upload a mapped CSV with Yahoo symbols ending .BO.")
    st.caption("No paid broker-data API token is required.")
if "nse_universe" not in st.session_state:
    cached=load_cached_nse_universe()
    if not cached.empty: st.session_state["nse_universe"]=cached
bse_df=pd.read_csv(bse_up).fillna("") if bse_up is not None else pd.DataFrame()
nse_df=st.session_state.get("nse_universe",pd.DataFrame())
custom=st.file_uploader("Upload custom stock universe CSV (optional)",type=["csv"],key="custom")
if custom: uni=pd.read_csv(custom).fillna("")
elif not nse_df.empty: uni=combine_universe(nse_df,bse_df)
else: uni=pd.read_csv("universe_template.csv").fillna("")
required=["symbol","company","exchange","sector","yahoo_symbol"]
if any(x not in uni.columns for x in required):
    st.error("Universe CSV must contain: "+", ".join(required)); st.stop()
st.warning("Yahoo Finance via yfinance is an unofficial public-data source. Quotes can be delayed, incomplete, rate-limited or unavailable. Treat this as a research shortlist, not an execution feed.")
if st.button("Run full scan",type="primary"):
    scan_uni=uni.copy()
    if max_symbols!="All": scan_uni=scan_uni.head(int(max_symbols))
    progress=st.progress(0,text=f"Downloading daily history for {len(scan_uni)} symbols...")
    status=st.empty()
    def update_progress(done,total,ok):
        progress.progress(done/max(1,total),text=f"Price history: {done}/{total} checked · {ok} usable")
        status.caption("Fetching daily candles concurrently. Headlines will be searched only for leading candidates.")
    data=fetch_many(scan_uni,progress_callback=update_progress,workers=6)
    nifty=fetch_nifty(); ctx=market_context(nifty)
    results=[]
    for meta,h in data:
        try:
            sc=score_stock(meta,h)
            results.append({**meta,**sc,"last_date":str(h.index[-1])[:10]})
        except Exception: pass
    # Only fetch headlines for a limited pre-ranked shortlist, not every stock.
    base=pd.DataFrame(results)
    if not base.empty:
        pre=base.sort_values("score",ascending=False).head(30)
        from radar.news import company_news
        news_progress=st.progress(0,text="Researching headlines for top 30 technical candidates...")
        for idx,(_,row) in enumerate(pre.iterrows(),1):
            try:
                headlines=company_news(row.get("company",row.get("symbol","")),limit=max_news)
                ns=max(-1,min(1,sum(x["sentiment"] for x in headlines)/max(1,len(headlines))))
                news_score=max(0,min(100,50+35*ns))
                mask=base["symbol"].eq(row["symbol"])
                base.loc[mask,"news"]=pd.Series([headlines]*int(mask.sum()),index=base.index[mask])
                base.loc[mask,"news_score"]=news_score
                base.loc[mask,"score"]=(.35*base.loc[mask,"trend_score"]+.30*base.loc[mask,"momentum_score"]+.20*base.loc[mask,"volume_score"]+.15*base.loc[mask,"rsi_score"])*.85+news_score*.15
                base.loc[mask,"reasons"]=pd.Series([row["reasons"]+[f"Headline score: {news_score:.0f}/100 ({len(headlines)} headlines)"]]*int(mask.sum()),index=base.index[mask])
            except Exception: pass
            news_progress.progress(idx/len(pre),text=f"News research: {idx}/{len(pre)} candidates")
    progress.empty(); status.empty()
    st.session_state["scan"]=(base,ctx,len(data),len(scan_uni))
if "scan" not in st.session_state:
    st.info("Upload a broad NSE/BSE universe CSV (Yahoo symbols such as RELIANCE.NS), then select Run full scan.")
    st.stop()
scan_state=st.session_state["scan"]
df,ctx,n_ok=scan_state[:3]
scanned_total=scan_state[3] if len(scan_state)>3 else n_ok
a,b,c=st.columns(3)
a.metric("Nifty regime",ctx["regime"].upper())
b.metric("Nifty 1-day",f"{ctx['nifty_change_1d']}%" if ctx["nifty_change_1d"] is not None else "N/A")
c.metric("Stocks with data",f"{n_ok}/{scanned_total}")
if df.empty: st.error("No stock data returned. Check Yahoo symbols and internet connection."); st.stop()
df=df[df.score>=min_score]
low=df[df.price<=1000].sort_values("score",ascending=False).head(5)
high=df[df.price>1000].sort_values("score",ascending=False).head(5)
def bucket(title,d):
    st.subheader(title)
    if d.empty: st.info("No stocks met the current score threshold in this bucket."); return
    st.dataframe(d[["symbol","company","price","change_1d_pct","ret5_pct","ret20_pct","rvol","rsi","score","risk","last_date"]].rename(columns={
        "symbol":"Symbol","company":"Company","price":"Price ₹","change_1d_pct":"1D %","ret5_pct":"5D %","ret20_pct":"20D %","rvol":"Rel.Vol","rsi":"RSI","score":"Score /100","risk":"Risk","last_date":"Data date"
    }),use_container_width=True,hide_index=True)
    for _,r in d.iterrows():
        with st.expander(f"{r['symbol']} · ₹{r['price']:.2f} · Radar {r['score']}/100"):
            st.write("**Score components**")
            st.json({k:r[k] for k in ["trend_score","momentum_score","volume_score","rsi_score","news_score"]})
            st.write("**Why it ranked**")
            for x in r["reasons"]: st.write("• "+x)
            st.write("**Recent headlines**")
            for n in r["news"]: st.markdown(f"- [{n['title']}]({n['link']}) · {n['published']}")
            st.caption("Score is a research ranking heuristic, not a calibrated probability or buy instruction.")
bucket("Top 5 · ₹1–₹1,000",low)
bucket("Top 5 · Above ₹1,000",high)
st.subheader("Telegram alerts")
if st.button("Send current top 5 + top 5 to Telegram"):
    lines=["INDIA STOCK RADAR — free-data shortlist","Research ranking only; verify quote freshness and risk."]
    for title,d in [("UP TO ₹1,000",low),("ABOVE ₹1,000",high)]:
        lines+=["",title]
        for i,(_,r) in enumerate(d.iterrows(),1):
            lines.append(f"{i}. {r['symbol']} ₹{r['price']:.2f} | score {r['score']}/100 | 5D {r['ret5_pct']:+.2f}%")
    try: send_telegram("\n".join(lines)); st.success("Telegram alert sent.")
    except Exception as e: st.error(str(e))
st.divider()
st.subheader("What this free edition includes / excludes")
st.write("- Uses concurrent daily OHLCV downloads (six workers) and searches news only for the top 30 technical candidates, reducing unnecessary requests. Yahoo Finance/yfinance is unofficial and may throttle or delay data.")
st.write("- Does not require Dhan Data API or Groww paid API. Dhan's free Trading API is not a substitute for its paid Data API.")
st.write("- Not yet includes official exchange delivery data, full FII/DII flow, validated corporate-action feed, audited financial statements, or institutional-grade news classification.")
st.write("- NSE EQ universe is sourced from the official NSE security CSV and cached locally. BSE coverage requires an optional mapped BSE CSV with Yahoo symbols ending .BO. Validate ticker mappings and duplicates.")

st.divider()
st.header("Broker accounts — optional read-only connection")
st.caption("Uses free Trading/portfolio APIs only. This panel never places, modifies or cancels orders. Tokens are read from your local .env file.")
if st.button("Fetch Dhan + Groww holdings, positions and available funds"):
    with st.spinner("Connecting to broker account APIs..."):
        st.session_state["broker_accounts"]=fetch_broker_accounts()
if "broker_accounts" in st.session_state:
    for broker,result in st.session_state["broker_accounts"].items():
        st.subheader(broker)
        if not result["ok"]:
            st.warning(result["error"])
            continue
        d=result["data"]
        st.success("Connected — read-only account data received")
        x,y,z=st.columns(3)
        x.metric("Holdings",len(d.get("holdings",[])))
        y.metric("Open positions",len(d.get("positions",[])))
        z.metric("Account data","Available")
        if d.get("holdings"):
            st.write("Holdings")
            st.dataframe(pd.DataFrame(d["holdings"]),use_container_width=True,hide_index=True)
        if d.get("positions"):
            st.write("Positions")
            st.dataframe(pd.DataFrame(d["positions"]),use_container_width=True,hide_index=True)
        with st.expander("Funds / margin response"):
            st.json(d.get("funds",{}))
