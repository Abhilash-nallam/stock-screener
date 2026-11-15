import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from radar.ledger import read_ledger
from radar.scan_service import refresh_both, refresh_exchange, run_scan, universe_status
from radar.telegram import send_telegram
from radar.brokers import fetch_broker_accounts
from radar.market_clock import format_market_status, get_market_status

load_dotenv()
st.set_page_config(page_title="India Stock Radar", page_icon="📡", layout="wide")
st.title("📡 India Stock Radar")
st.caption("NSE + BSE daily research · free public 5-minute confirmation · no broker orders")

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
    st.caption("Yahoo public candles may be delayed. Confirm the current price and bid/ask in your broker before acting.")

session_now = get_market_status()
if session_now.get("phase") == "open":
    st.success(f"NSE cash market open · {session_now.get('local_time')} IST")
else:
    st.info(format_market_status(session_now))
st.warning(
    "This scanner uses free Yahoo Finance daily and completed 5-minute candles. "
    "The 5-minute close is not a guaranteed live exchange quote; data may be delayed or unavailable. "
    "Verify the live price, spread, news and risk in your broker app before trading."
)

if st.button(f"Run {scan_size}-stock scan", type="primary", use_container_width=True):
    progress = st.progress(0, text=f"Starting {scan_size}-stock scan...")
    try:
        result = run_scan(limit=scan_size, min_score=min_score, news_limit=news_limit, workers=6)
        st.session_state["scan_result"] = result
        progress.progress(1.0, text="Market/session and data checks completed")
        if result.get("live_ready"):
            st.success(
                f"Scan completed: {result.get('live_confirmed_count', 0)} intraday-confirmed candidates "
                f"from {result.get('live_researched_count', 0)} researched leaders."
            )
        else:
            st.warning(result.get("live_error", "No scan report was generated."))
    except Exception as exc:
        progress.empty()
        st.error(f"Scan failed: {exc}")

result = st.session_state.get("scan_result")
if result:
    session = result.get("market_session") or {}
    if session.get("phase") != "open":
        st.info(format_market_status(session))
    elif not result.get("live_ready", False):
        st.warning(result.get("live_error", "Live intraday data is unavailable."))
    else:
        market = result.get("market") or {}
        a, b, c, d = st.columns(4)
        a.metric("Nifty daily regime", str(market.get("regime", "unknown")).upper())
        nifty_change = result.get("live_nifty_change_pct")
        b.metric("Nifty latest 5m move", f"{nifty_change:+.2f}%" if nifty_change is not None else "N/A")
        c.metric("Intraday-confirmed candidates", int(result.get("live_confirmed_count", 0)))
        d.metric("5m shortlist coverage", f"{result.get('live_coverage_pct', 0):.1f}%")
        st.caption(
            f"Last daily baseline: {result.get('data_date', 'n/a')} · "
            f"Daily histories: {result.get('success_count', 0)}/{result.get('selected_count', 0)} · "
            f"Intraday research: {result.get('live_researched_count', 0)} leaders · "
            f"Public candle age for Nifty: {result.get('live_candle_age_seconds', 'n/a')} sec"
        )

        def fmt_price(value):
            try:
                value = float(value)
                return f"₹{value:,.2f}" if pd.notna(value) else "n/a"
            except (TypeError, ValueError):
                return "n/a"

        def show_bucket(title, frame):
            st.subheader(title)
            if frame is None or frame.empty:
                st.info("No stock in this price band passed every intraday confirmation gate. No trade is a valid result.")
                return
            cols = [
                "symbol", "company", "exchange", "live_price", "live_score",
                "risk", "live_change_pct", "live_5m_momentum_pct",
                "live_vwap_distance_pct", "live_quote_time", "rsi",
            ]
            display = frame.copy()
            display["live_price_display"] = display["live_price"].map(fmt_price)
            display["live_price"] = display["live_price_display"]
            labels = {
                "symbol": "Symbol", "company": "Company", "exchange": "Exchange",
                "live_price": "Latest 5m close", "live_score": "Intraday score",
                "risk": "Daily risk", "live_change_pct": "vs prior close %",
                "live_5m_momentum_pct": "3-bar 5m momentum %",
                "live_vwap_distance_pct": "vs VWAP %", "live_quote_time": "Candle end",
                "rsi": "Daily RSI",
            }
            available = [column for column in cols if column in display.columns]
            st.dataframe(
                display[available].rename(columns=labels),
                use_container_width=True,
                hide_index=True,
            )
            for _, row in frame.iterrows():
                with st.expander(
                    f"{row['symbol']} · {fmt_price(row.get('live_price'))} · "
                    f"Intraday score {row.get('live_score', 'n/a')}/100"
                ):
                    st.write(f"**Decision:** {row.get('live_status', 'WAIT')} · **Risk:** {row.get('risk', 'Unknown')}")
                    st.write(f"**Last completed 5m candle:** {row.get('live_quote_time', 'n/a')} · "
                             f"**Age:** {row.get('live_quote_age_seconds', 'n/a')} seconds")
                    st.write("**Live-reference levels (not live exchange quotes or orders)**")
                    x, y, z, q = st.columns(4)
                    x.metric("Entry zone", f"{fmt_price(row.get('live_entry_low'))} – {fmt_price(row.get('live_entry_high'))}")
                    y.metric("Stop reference", fmt_price(row.get("live_stop")))
                    z.metric("Target 1", fmt_price(row.get("live_target1")))
                    q.metric("Target 2", fmt_price(row.get("live_target2")))
                    st.write("**Why it passed the filters**")
                    st.write(row.get("live_reason", "No additional explanation"))
                    for flag in row.get("flags", []):
                        st.warning(flag)
                    for headline in row.get("news", []):
                        title = headline.get("title", "News")
                        link = headline.get("link", "")
                        published = headline.get("published", "date n/a")
                        if str(link).startswith(("https://", "http://")):
                            st.markdown(f"- [{title}]({link}) · {published}")
                        else:
                            st.write(f"- {title} · {published}")

        show_bucket("🟢 Intraday-confirmed · Price ≤ ₹1,000", result.get("low"))
        show_bucket("🔵 Intraday-confirmed · Price > ₹1,000", result.get("high"))

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
                    message = (
                        f"🇮🇳 INDIA STOCK RADAR · {result.get('data_date', 'n/a')}\n"
                        f"Nifty daily regime {str(market.get('regime', 'unknown')).upper()} · "
                        f"latest Nifty 5m move {nifty_change}%\n"
                        f"Intraday confirmed: {result.get('live_confirmed_count', 0)}. "
                        "Check Telegram for detailed cards."
                    )
                    send_telegram(message)
                    st.success("Telegram summary sent.")
                except Exception as exc:
                    st.error(f"Telegram send failed: {exc}")

        st.divider()
        st.subheader("Forward-test ledger")
        ledger_frame = read_ledger()
        if ledger_frame.empty:
            st.info("No picks have been logged yet.")
        else:
            for column in ("return_5d_pct", "return_20d_pct"):
                if column not in ledger_frame.columns:
                    ledger_frame[column] = pd.NA
            ret5 = pd.to_numeric(ledger_frame["return_5d_pct"], errors="coerce").dropna()
            ret20 = pd.to_numeric(ledger_frame["return_20d_pct"], errors="coerce").dropna()
            m1, m2, m3 = st.columns(3)
            m1.metric("Logged picks", len(ledger_frame))
            m2.metric("5-session observations", len(ret5))
            m3.metric("20-session observations", len(ret20))
            if not ret5.empty:
                st.metric("5-session positive outcomes", f"{(ret5 > 0).mean()*100:.1f}%")
            st.dataframe(
                ledger_frame.sort_values("asof_date", ascending=False).head(100),
                use_container_width=True, hide_index=True
            )

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
