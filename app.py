import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from radar.ledger import read_ledger
from radar.scan_service import refresh_both, refresh_exchange, run_scan, universe_status
from radar.telegram import send_telegram
from radar.brokers import fetch_broker_accounts

load_dotenv()
st.set_page_config(page_title="India Stock Radar", page_icon="📡", layout="wide")
st.title("📡 India Stock Radar")
st.caption("NSE + BSE daily market research · relative strength · risk-aware shortlist · Telegram controls")

with st.sidebar:
    st.header("Scan settings")
    st.caption("Scan the combined NSE + BSE universe")
    scan_size = st.selectbox("Stocks per scan", [250, 500], index=0)
    min_score = st.slider("Minimum radar score", 0, 100, 60)
    news_limit = st.slider("Headlines per leading stock", 3, 10, 6)

    st.divider()
    st.subheader("Exchange universes")
    if st.button("Refresh NSE + BSE lists", use_container_width=True):
        with st.spinner("Refreshing official/public exchange lists..."):
            refresh_result = refresh_both()
        for name in ("nse", "bse"):
            if name in refresh_result["refreshed"]:
                st.success(f"{name.upper()}: {refresh_result['refreshed'][name]['count']:,} securities")
            elif name in refresh_result["errors"]:
                st.warning(f"{name.upper()} refresh failed: {refresh_result['errors'][name]}")
    if st.button("Refresh NSE only", use_container_width=True):
        try:
            st.success(f"NSE refreshed: {refresh_exchange('nse')['count']:,} securities")
        except Exception as exc:
            st.error(f"NSE refresh failed: {exc}")
    if st.button("Refresh BSE only", use_container_width=True):
        try:
            st.success(f"BSE refreshed: {refresh_exchange('bse')['count']:,} securities")
        except Exception as exc:
            st.error(f"BSE refresh failed: {exc}")
    counts = universe_status()
    st.caption(f"Cached securities: NSE {counts['nse']:,} · BSE {counts['bse']:,} · Combined {counts['combined']:,}")
    st.caption("Yahoo daily candles are research data, not live execution quotes.")

st.warning(
    "Prices and trade-planning levels use the last available daily close. Yahoo Finance via yfinance "
    "is unofficial and may be delayed, incomplete, throttled or unavailable. Verify live quotes, "
    "exchange filings and risk before placing any order."
)

if st.button(f"Run {scan_size}-stock scan", type="primary", use_container_width=True):
    progress = st.progress(0, text=f"Starting {scan_size}-stock scan...")
    try:
        result = run_scan(limit=scan_size, min_score=min_score, news_limit=news_limit, workers=6)
        st.session_state["scan_result"] = result
        progress.progress(1.0, text=f"Completed: {result['success_count']}/{result['selected_count']} usable histories")
        st.success("Scan completed.")
    except Exception as exc:
        progress.empty()
        st.error(f"Scan failed: {exc}")

result = st.session_state.get("scan_result")
if result:
    market = result["market"]
    a, b, c, d = st.columns(4)
    a.metric("Nifty regime", str(market["regime"]).upper())
    b.metric("Nifty 1-day", f"{market['nifty_change_1d']}%" if market["nifty_change_1d"] is not None else "N/A")
    c.metric("Nifty 5-day", f"{market['nifty_change_5d']}%" if market["nifty_change_5d"] is not None else "N/A")
    d.metric("Daily histories", f"{result['success_count']}/{result['selected_count']}")
    st.caption(
        f"Universe: {result['universe_count']:,} unique securities · "
        f"{result['candidate_count']:,} watchlist candidates · "
        f"{result['excluded_count']:,} rejected by data-quality/liquidity/event filters · "
        f"Data date: {result['data_date']}"
    )

    def show_bucket(title, frame):
        st.subheader(title)
        if frame.empty:
            st.info("No stock in this price band passed the current score and risk filters.")
            return
        cols = ["symbol", "company", "exchange", "price", "score", "risk", "ret1_pct",
                "ret5_pct", "ret20_pct", "rvol", "rsi", "data_date"]
        display = frame.copy()
        display["ret1_pct"] = display["change_1d_pct"]
        labels = {"symbol": "Symbol", "company": "Company", "exchange": "Exchange",
                  "price": "Close ₹", "score": "Score", "risk": "Risk", "ret1_pct": "1D %",
                  "ret5_pct": "5D %", "ret20_pct": "20D %", "rvol": "Rel.Vol",
                  "rsi": "RSI", "data_date": "Data date"}
        st.dataframe(display[cols].rename(columns=labels), use_container_width=True, hide_index=True)
        for _, row in frame.iterrows():
            with st.expander(f"{row['symbol']} · ₹{row['price']:.2f} · {row['score']}/100"):
                st.write(f"**Setup:** {row['setup_status']} · **Risk:** {row['risk']}")
                st.write("**Close-based planning levels — not live prices or orders**")
                x, y, z, q = st.columns(4)
                x.metric("Entry reference", f"₹{row['entry_low']:.2f}–₹{row['entry_high']:.2f}")
                y.metric("Stop reference", f"₹{row['stop_loss']:.2f}")
                z.metric("Target 1", f"₹{row['target1']:.2f}")
                q.metric("Target 2", f"₹{row['target2']:.2f}")
                st.write("**Why it ranked**")
                for reason in row["reasons"]:
                    st.write(f"- {reason}")
                for flag in row.get("flags", []):
                    st.warning(flag)
                for headline in row.get("news", []):
                    st.markdown(f"- [{headline['title']}]({headline['link']}) · {headline['published']}")

    show_bucket("Top 5 · Price up to ₹1,000", result["low"])
    show_bucket("Top 5 · Price above ₹1,000", result["high"])

    st.subheader("Telegram alerts")
    test_col, send_col = st.columns(2)
    with test_col:
        if st.button("Test Telegram connection"):
            try:
                send_telegram("✅ India Stock Radar test successful. Telegram delivery is working.")
                st.success("Test message delivered.")
            except Exception as exc:
                st.error(f"Telegram test failed: {exc}")
    with send_col:
        if st.button("Send current shortlist to Telegram"):
            try:
                # Send concise summary; detailed rich cards are available in the Telegram bot.
                message = (
                    f"🇮🇳 INDIA STOCK RADAR · {result['data_date']}\n"
                    f"Nifty {market['regime'].upper()} · "
                    f"1D {market['nifty_change_1d']}% · 5D {market['nifty_change_5d']}%\n"
                    f"Scan {result['success_count']}/{result['selected_count']} stocks. "
                    "Use /scan in Telegram for the detailed colour-coded report."
                )
                send_telegram(message)
                st.success("Telegram summary sent.")
            except Exception as exc:
                st.error(f"Telegram send failed: {exc}")

    st.divider()
    st.subheader("Forward-test ledger")
    ledger = read_ledger()
    if ledger.empty:
        st.info("No picks have been logged yet.")
    else:
        ret5 = pd.to_numeric(ledger["return_5d_pct"], errors="coerce").dropna()
        ret20 = pd.to_numeric(ledger["return_20d_pct"], errors="coerce").dropna()
        m1, m2, m3 = st.columns(3)
        m1.metric("Logged picks", len(ledger))
        m2.metric("5-session observations", len(ret5))
        m3.metric("20-session observations", len(ret20))
        if not ret5.empty:
            m1.metric("5-session positive outcomes", f"{(ret5 > 0).mean()*100:.1f}%")
        st.dataframe(ledger.sort_values("asof_date", ascending=False).head(100),
                     use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "Data limitations: no official delivery-volume, full FII/DII, audited fundamental or "
    "corporate-announcement classifier is integrated. Model scores are rankings, not "
    "probabilities of profit. Dhan/Groww panels, when configured, are read-only."
)

st.header("Broker accounts — optional read-only connection")
if st.button("Fetch Dhan + Groww holdings, positions and funds"):
    with st.spinner("Connecting to read-only broker APIs..."):
        st.session_state["broker_accounts"] = fetch_broker_accounts()
if "broker_accounts" in st.session_state:
    for broker, response in st.session_state["broker_accounts"].items():
        st.subheader(broker)
        if not response["ok"]:
            st.warning(response["error"])
            continue
        data = response["data"]
        st.success("Connected — read-only account data received")
        st.write(f"Holdings: {len(data.get('holdings', []))} · Open positions: {len(data.get('positions', []))}")
        if data.get("holdings"):
            st.dataframe(pd.DataFrame(data["holdings"]), use_container_width=True, hide_index=True)
        if data.get("positions"):
            st.dataframe(pd.DataFrame(data["positions"]), use_container_width=True, hide_index=True)
