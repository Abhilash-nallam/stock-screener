import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from radar.free_data import fetch_many, fetch_nifty, market_context
from radar.scoring import score_stock, apply_news_overlay
from radar.ledger import save_daily_picks, read_ledger
from radar.telegram import send_telegram
from radar.brokers import fetch_broker_accounts
from radar.universe import fetch_nse_universe, load_cached_nse_universe, combine_universe

load_dotenv()
st.set_page_config(page_title="India Stock Radar", page_icon="📡", layout="wide")
st.title("📡 India Stock Radar — Recommendation Model v2")
st.caption("NSE/BSE daily-candle research · Nifty-relative scoring · risk levels · forward-test ledger")

with st.sidebar:
    st.header("Scan settings")
    st.caption("Automatic NSE EQ universe + optional BSE/custom list")
    if st.button("Refresh official NSE equity list"):
        try:
            st.session_state["nse_universe"] = fetch_nse_universe()
            st.success(f"Loaded {len(st.session_state['nse_universe'])} NSE EQ symbols")
        except Exception as exc:
            cached = load_cached_nse_universe()
            if not cached.empty:
                st.session_state["nse_universe"] = cached
                st.warning(f"NSE refresh failed; using cached list ({len(cached)} symbols): {exc}")
            else:
                st.error(f"NSE download failed: {exc}")
    bse_upload = st.file_uploader("Optional BSE mapped CSV", type=["csv"], key="bse_file")
    custom_upload = st.file_uploader("Optional custom universe CSV", type=["csv"], key="custom")
    min_score = st.slider("Minimum radar score", 0, 100, 60)
    max_news = st.slider("Headlines per candidate", 3, 10, 6)
    max_symbols = st.selectbox("Maximum symbols per scan", ["250", "500", "1000", "All"], index=1)
    st.caption("Yahoo daily candles are for research, not live order execution.")

if "nse_universe" not in st.session_state:
    cached = load_cached_nse_universe()
    if not cached.empty:
        st.session_state["nse_universe"] = cached

bse_df = pd.read_csv(bse_upload).fillna("") if bse_upload is not None else pd.DataFrame()
nse_df = st.session_state.get("nse_universe", pd.DataFrame())
if custom_upload is not None:
    universe = pd.read_csv(custom_upload).fillna("")
elif not nse_df.empty:
    universe = combine_universe(nse_df, bse_df)
else:
    universe = pd.read_csv("universe_template.csv").fillna("")

required = ["symbol", "company", "exchange", "sector", "yahoo_symbol"]
if any(column not in universe.columns for column in required):
    st.error("Universe CSV must contain: " + ", ".join(required))
    st.stop()

st.warning(
    "Yahoo Finance through yfinance is unofficial and can be delayed, incomplete, throttled, "
    "or unavailable. Prices and levels below use the last available daily close. "
    "Do not treat them as live quotes or automatic buy orders."
)

if st.button("Run full scan", type="primary"):
    scan_universe = universe.drop_duplicates("yahoo_symbol").copy()
    if max_symbols != "All":
        scan_universe = scan_universe.head(int(max_symbols))
    progress = st.progress(0, text=f"Downloading daily history for {len(scan_universe)} symbols...")
    status = st.empty()

    def update_progress(done, total, usable):
        progress.progress(done / max(1, total),
                          text=f"Price history: {done}/{total} checked · {usable} usable")
        status.caption("Concurrent daily candles; news requests are limited to leading candidates.")

    histories_data = fetch_many(scan_universe, progress_callback=update_progress, workers=6)
    market = market_context(fetch_nifty())
    results, histories = [], {}
    for meta, history in histories_data:
        try:
            scored = score_stock(meta, history, market)
            results.append({**meta, **scored})
            histories[str(meta.get("symbol", ""))] = history
        except Exception:
            continue

    base = pd.DataFrame(results)
    if not base.empty:
        candidates = base.sort_values("score", ascending=False).head(30)
        from radar.news import company_news
        news_progress = st.progress(0, text="Checking headlines for top 30 candidates...")
        for count, (row_index, row) in enumerate(candidates.iterrows(), 1):
            headlines = []
            try:
                headlines = company_news(row.get("company", row.get("symbol", "")), limit=max_news)
            except Exception:
                pass
            adjusted, news_score, adjustment = apply_news_overlay(float(row["base_score"]), headlines)
            base.at[row_index, "score"] = adjusted
            base.at[row_index, "news_score"] = news_score
            base.at[row_index, "news_adjustment"] = adjustment
            base.at[row_index, "news"] = headlines
            if news_score is not None:
                base.at[row_index, "reasons"] = list(row["reasons"]) + [
                    f"Headline keyword overlay: {news_score:.0f}/100 ({adjustment:+.1f} score points; low weight)"
                ]
            news_progress.progress(count / len(candidates),
                                   text=f"News: {count}/{len(candidates)} candidates")

    progress.empty()
    status.empty()
    st.session_state["scan"] = (base, market, len(histories_data), len(scan_universe), histories)

if "scan" not in st.session_state:
    st.info("Load the NSE universe or upload a mapped stock universe, then select Run full scan.")
    st.stop()

df, market, successful, total, histories = st.session_state["scan"]
a, b, c, d = st.columns(4)
a.metric("Nifty regime", str(market["regime"]).upper())
b.metric("Nifty 1-day", f"{market['nifty_change_1d']}%" if market["nifty_change_1d"] is not None else "N/A")
c.metric("Nifty 5-day", f"{market['nifty_change_5d']}%" if market["nifty_change_5d"] is not None else "N/A")
d.metric("Stocks with data", f"{successful}/{total}")

if df.empty:
    st.error("No usable daily history returned. Check Yahoo symbols, internet connection or throttling.")
    st.stop()

# Do not force five names: exclude stale prices, thin turnover and extreme event gaps.
eligible = df[(df["eligible"] == True) & (df["score"] >= min_score)].copy()
low = eligible[eligible["price"] <= 1000].sort_values("score", ascending=False).head(5)
high = eligible[eligible["price"] > 1000].sort_values("score", ascending=False).head(5)
excluded = int((~df["eligible"].astype(bool)).sum())
st.caption(
    f"Eligible after data-quality and liquidity checks: {len(eligible)} · "
    f"Excluded for stale data, low liquidity or extreme event gaps: {excluded}. "
    "Fewer than five names is intentional when the filters reject the rest."
)

picked = pd.concat([low, high], ignore_index=True)
if not picked.empty:
    save_daily_picks(picked, histories, market["regime"])

def show_bucket(title, frame):
    st.subheader(title)
    if frame.empty:
        st.info("No candidates passed the score, freshness and liquidity filters in this price band.")
        return
    columns = [
        "symbol", "company", "price", "score", "setup_status", "risk",
        "ret5_pct", "ret20_pct", "rvol", "rsi", "atr_pct", "turnover20", "data_date",
    ]
    labels = {
        "symbol": "Symbol", "company": "Company", "price": "Close ₹", "score": "Score",
        "setup_status": "Setup", "risk": "Risk", "ret5_pct": "5D %", "ret20_pct": "20D %",
        "rvol": "Rel.Vol", "rsi": "RSI", "atr_pct": "ATR %", "turnover20": "Median turnover ₹",
        "data_date": "Price date",
    }
    st.dataframe(frame[columns].rename(columns=labels), use_container_width=True, hide_index=True)
    for _, row in frame.iterrows():
        with st.expander(f"{row['symbol']} · ₹{row['price']:.2f} · Score {row['score']}/100"):
            st.write(f"**Setup:** {row['setup_status']}  |  **Risk:** {row['risk']}")
            st.write("**Close-based planning levels — not live quotes or orders**")
            x, y, z, q = st.columns(4)
            x.metric("Reference entry zone", f"₹{row['entry_low']:.2f}–₹{row['entry_high']:.2f}")
            y.metric("Stop reference", f"₹{row['stop_loss']:.2f}")
            z.metric("Target 1", f"₹{row['target1']:.2f}")
            q.metric("Target 2", f"₹{row['target2']:.2f}")
            component_keys = [
                "trend_score", "momentum_score", "relative_strength_score", "volume_score",
                "rsi_score", "liquidity_score", "volatility_score", "market_score",
            ]
            st.write("**Score components**")
            st.json({key: row.get(key) for key in component_keys})
            st.write("**Reasons**")
            for reason in row["reasons"]:
                st.write("• " + reason)
            for flag in row.get("flags", []):
                st.warning(flag)
            st.write("**Recent headlines**")
            for headline in row.get("news", []):
                st.markdown(f"- [{headline['title']}]({headline['link']}) · {headline['published']}")
            if not row.get("news"):
                st.caption("No headline overlay was available for this candidate.")
            st.caption("Ranking score is a heuristic, not a probability of profit or a buy instruction.")

show_bucket("Top 5 · Price up to ₹1,000", low)
show_bucket("Top 5 · Price above ₹1,000", high)

st.subheader("Telegram alerts")
if st.button("Send current shortlist to Telegram"):
    lines = [
        "INDIA STOCK RADAR — recommendation model v2",
        "Daily-close research only; verify fresh quotes, filings and risk before trading.",
        f"Nifty regime: {market['regime'].upper()}",
    ]
    for label, frame in [("UP TO ₹1,000", low), ("ABOVE ₹1,000", high)]:
        lines.extend(["", label])
        if frame.empty:
            lines.append("No candidates passed filters.")
        for number, (_, row) in enumerate(frame.iterrows(), 1):
            lines.append(
                f"{number}. {row['symbol']} ₹{row['price']:.2f} | score {row['score']}/100 | "
                f"{row['setup_status']} | SL ref ₹{row['stop_loss']:.2f} | "
                f"T1 ₹{row['target1']:.2f} | data {row['data_date']}"
            )
    try:
        send_telegram("\n".join(lines))
        st.success("Telegram alert sent.")
    except Exception as exc:
        st.error(str(exc))

st.divider()
st.subheader("Forward-test ledger")
st.caption(
    "Stores daily shortlist snapshots and tracks 5-/20-session forward close returns when "
    "enough daily bars become available. This is not a broker execution record."
)
ledger = read_ledger()
if ledger.empty:
    st.info("No picks logged yet. Run a scan to begin the prospective record.")
else:
    returns5 = pd.to_numeric(ledger["return_5d_pct"], errors="coerce").dropna()
    returns20 = pd.to_numeric(ledger["return_20d_pct"], errors="coerce").dropna()
    m1, m2, m3 = st.columns(3)
    m1.metric("Logged picks", len(ledger))
    m2.metric("5-session observations", len(returns5))
    m3.metric("20-session observations", len(returns20))
    if not returns5.empty:
        st.metric("5-session positive outcomes", f"{(returns5 > 0).mean() * 100:.1f}%")
    st.dataframe(ledger.sort_values("asof_date", ascending=False).head(100),
                 use_container_width=True, hide_index=True)

st.divider()
st.subheader("Data boundaries")
st.write("- Yahoo Finance via yfinance supplies adjusted daily OHLCV; freshness and completeness vary.")
st.write("- Model v2 adds Nifty-relative strength, median-volume checks, traded-value liquidity, ATR volatility, gap checks, data-age gates, close-based levels and a forward-test ledger.")
st.write("- News keyword sentiment is capped at +/-4 score points and is not a substitute for reading articles or company filings.")
st.write("- No official delivery data, full FII/DII series, audited-fundamentals dataset or corporate-announcement feed is integrated. Missing inputs are not treated as bullish.")
st.write("- Dhan/Groww panels remain read-only account views. No orders are placed, modified or cancelled.")

st.divider()
st.header("Broker accounts — optional read-only connection")
st.caption("Uses local .env credentials for holdings, positions and funds. No trading actions are implemented.")
if st.button("Fetch Dhan + Groww holdings, positions and available funds"):
    with st.spinner("Connecting to broker account APIs..."):
        st.session_state["broker_accounts"] = fetch_broker_accounts()
if "broker_accounts" in st.session_state:
    for broker, result in st.session_state["broker_accounts"].items():
        st.subheader(broker)
        if not result["ok"]:
            st.warning(result["error"])
            continue
        data = result["data"]
        st.success("Connected — read-only account data received")
        x, y, z = st.columns(3)
        x.metric("Holdings", len(data.get("holdings", [])))
        y.metric("Open positions", len(data.get("positions", [])))
        z.metric("Account data", "Available")
        if data.get("holdings"):
            st.dataframe(pd.DataFrame(data["holdings"]), use_container_width=True, hide_index=True)
        if data.get("positions"):
            st.dataframe(pd.DataFrame(data["positions"]), use_container_width=True, hide_index=True)
        with st.expander("Funds / margin response"):
            st.json(data.get("funds", {}))
