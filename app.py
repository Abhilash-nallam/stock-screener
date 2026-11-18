import hmac
import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from radar.ledger import read_ledger
from radar.scan_service import refresh_both, refresh_exchange, run_scan, universe_status
from radar.market_clock import format_market_status, get_market_status

load_dotenv()
st.set_page_config(
    page_title="India Stock Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.4rem; padding-bottom: 2.5rem; max-width: 1600px;}
      [data-testid="stMetric"] {background: rgba(128,128,128,.07); border: 1px solid rgba(128,128,128,.16); padding: 13px 15px; border-radius: 12px;}
      [data-testid="stMetricLabel"] {font-size: .82rem;}
      div[data-testid="stDataFrame"] {border: 1px solid rgba(128,128,128,.18); border-radius: 10px;}
      .radar-muted {opacity: .72; font-size: .88rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📡 India Stock Radar")
st.caption("NSE + BSE research terminal · delivery / swing watchlists · intraday confirmation · no broker orders")

with st.sidebar:
    st.header("⚙️ Scan controls")
    st.caption("Scans use the combined NSE + BSE universe.")
    scan_size = st.selectbox("Stocks per scan", [250, 500], index=0)
    min_score = st.slider("Minimum daily score", 0, 100, 60)
    news_limit = st.slider("Headlines per leading stock", 3, 10, 6)

    dashboard_password = os.getenv("RADAR_DASHBOARD_PASSWORD", "").strip()
    try:
        dashboard_password = dashboard_password or str(
            st.secrets.get("RADAR_DASHBOARD_PASSWORD", "")
        ).strip()
    except Exception:
        pass
    entered_password = st.text_input("Private dashboard password", type="password")
    admin_enabled = bool(
        dashboard_password
        and entered_password
        and hmac.compare_digest(entered_password, dashboard_password)
    )
    if admin_enabled:
        st.success("Private scan controls unlocked for this session.")
    elif dashboard_password:
        st.caption("Enter the configured password to enable manual scans.")
    else:
        st.caption("Read-only mode. Configure RADAR_DASHBOARD_PASSWORD to enable manual scans.")

    st.divider()
    st.subheader("Exchange universes")
    counts = universe_status()
    nse_col, bse_col = st.columns(2)
    nse_col.metric("NSE cached", f"{counts['nse']:,}")
    bse_col.metric("BSE cached", f"{counts['bse']:,}")
    st.caption(f"Combined cached securities: {counts['combined']:,}")
    if admin_enabled:
        if st.button("Refresh NSE + BSE", use_container_width=True):
            with st.spinner("Refreshing public exchange lists..."):
                refresh_result = refresh_both()
            for name in ("nse", "bse"):
                if name in refresh_result["refreshed"]:
                    st.success(f"{name.upper()}: {refresh_result['refreshed'][name]['count']:,} securities")
                elif name in refresh_result["errors"]:
                    st.warning(f"{name.upper()} refresh failed: {refresh_result['errors'][name]}")
        left, right = st.columns(2)
        if left.button("Refresh NSE", use_container_width=True):
            try:
                st.success(f"NSE refreshed: {refresh_exchange('nse')['count']:,}")
            except Exception as exc:
                st.error(f"NSE refresh failed: {exc}")
        if right.button("Refresh BSE", use_container_width=True):
            try:
                st.success(f"BSE refreshed: {refresh_exchange('bse')['count']:,}")
            except Exception as exc:
                st.error(f"BSE refresh failed: {exc}")
    else:
        st.caption("Universe refresh is disabled in public read-only mode.")

    st.divider()
    st.caption("Yahoo Finance is an unofficial, potentially delayed data source. Verify live quotes and bid/ask in your broker before acting.")

session_now = get_market_status()
phase = str(session_now.get("phase", "unknown"))
if phase == "open":
    st.success(f"🟢 NSE cash market open · {session_now.get('local_time', 'n/a')} IST")
else:
    st.info(format_market_status(session_now))

st.warning(
    "Risk notice: daily prices and completed 5-minute candles from Yahoo Finance are not guaranteed live exchange quotes. "
    "This dashboard is research only; it does not place orders or promise returns."
)

scan_col, status_col = st.columns([1, 2])
with scan_col:
    scan_clicked = st.button(
        f"🚀 Run {scan_size}-stock scan",
        type="primary",
        use_container_width=True,
        disabled=not admin_enabled,
    )
with status_col:
    if not admin_enabled:
        st.caption("Manual scans require the private dashboard password. Telegram scanning remains separate.")

if scan_clicked:
    progress = st.progress(0, text=f"Starting {scan_size}-stock research scan...")
    try:
        result = run_scan(
            limit=scan_size,
            min_score=min_score,
            news_limit=news_limit,
            workers=6,
        )
        st.session_state["scan_result"] = result
        st.session_state["scan_completed_at"] = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%d %b %Y, %H:%M IST")
        progress.progress(1.0, text="Research scan completed")
    except Exception as exc:
        progress.empty()
        st.error(f"Scan failed: {exc}")

result = st.session_state.get("scan_result")
if not result:
    st.divider()
    st.subheader("Ready for research")
    st.write("Run a scan from the sidebar controls or use your private Telegram bot. Results will appear here after a scan.")
    st.caption("The dashboard keeps the last result in this browser session while it remains active.")
else:
    session = result.get("market_session") or {}
    market = result.get("market") or {}
    delivery_low = result.get("delivery_low")
    delivery_high = result.get("delivery_high")
    low_live = result.get("low")
    high_live = result.get("high")

    def as_frame(value):
        return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()

    delivery_low = as_frame(delivery_low)
    delivery_high = as_frame(delivery_high)
    low_live = as_frame(low_live)
    high_live = as_frame(high_live)

    def fmt_price(value):
        try:
            number = float(value)
            return f"₹{number:,.2f}" if pd.notna(number) else "—"
        except (TypeError, ValueError):
            return "—"

    def fmt_pct(value):
        try:
            number = float(value)
            return f"{number:+.2f}%" if pd.notna(number) else "—"
        except (TypeError, ValueError):
            return "—"

    def render_stock_table(frame, kind="daily"):
        if frame.empty:
            st.info("No candidates passed the current filters. No trade is a valid result.")
            return
        display = frame.copy()
        if kind == "live":
            preferred = [
                "symbol", "company", "exchange", "live_price", "live_score", "risk",
                "live_change_pct", "live_5m_momentum_pct", "live_vwap_distance_pct",
                "live_quote_time", "rsi",
            ]
            labels = {
                "symbol": "Symbol", "company": "Company", "exchange": "Exchange",
                "live_price": "Latest 5m close", "live_score": "Intraday score",
                "risk": "Daily risk", "live_change_pct": "Day change",
                "live_5m_momentum_pct": "3-bar momentum", "live_vwap_distance_pct": "vs VWAP",
                "live_quote_time": "Candle time", "rsi": "Daily RSI",
            }
            for col in ("live_change_pct", "live_5m_momentum_pct", "live_vwap_distance_pct"):
                if col in display:
                    display[col] = display[col].map(fmt_pct)
            if "live_price" in display:
                display["live_price"] = display["live_price"].map(fmt_price)
        else:
            preferred = [
                "symbol", "company", "exchange", "price", "score", "risk",
                "change_1d_pct", "ret5_pct", "ret20_pct", "rsi", "rvol",
                "entry_low", "entry_high", "stop_loss", "target1", "target2",
            ]
            labels = {
                "symbol": "Symbol", "company": "Company", "exchange": "Exchange",
                "price": "Daily close", "score": "Daily score", "risk": "Risk",
                "change_1d_pct": "1D", "ret5_pct": "5D", "ret20_pct": "20D",
                "rsi": "RSI", "rvol": "Rel. volume",
                "entry_low": "Entry low", "entry_high": "Entry high",
                "stop_loss": "Stop ref.", "target1": "Target 1", "target2": "Target 2",
            }
            if "price" in display:
                display["price"] = display["price"].map(fmt_price)
            for col in ("change_1d_pct", "ret5_pct", "ret20_pct"):
                if col in display:
                    display[col] = display[col].map(fmt_pct)
        available = [column for column in preferred if column in display.columns]
        st.dataframe(
            display[available].rename(columns=labels),
            use_container_width=True,
            hide_index=True,
        )

    def render_delivery_bucket(title, frame):
        st.subheader(title)
        render_stock_table(frame, "daily")
        if not frame.empty:
            for _, row in frame.iterrows():
                with st.expander(f"{row.get('symbol', 'Stock')} · score {row.get('score', '—')}/100 · {row.get('risk', 'Risk n/a')} risk"):
                    st.write(f"**Company:** {row.get('company', 'n/a')} · **Exchange:** {row.get('exchange', 'n/a')}")
                    st.write(f"**Daily close:** {fmt_price(row.get('price'))} · **Data date:** {row.get('data_date', 'n/a')}")
                    st.write(f"**Setup:** {row.get('setup_status', 'n/a')}")
                    st.write(f"**Entry reference:** {fmt_price(row.get('entry_low'))} – {fmt_price(row.get('entry_high'))} · **Stop:** {fmt_price(row.get('stop_loss'))}")
                    st.write(f"**Targets:** {fmt_price(row.get('target1'))} / {fmt_price(row.get('target2'))}")
                    for flag in row.get("flags", []) if isinstance(row.get("flags", []), list) else []:
                        st.warning(flag)
                    for reason in row.get("reasons", []) if isinstance(row.get("reasons", []), list) else []:
                        st.caption(f"• {reason}")

    def render_live_bucket(title, frame):
        st.subheader(title)
        render_stock_table(frame, "live")
        if frame.empty:
            return
        for _, row in frame.iterrows():
            with st.expander(f"{row.get('symbol', 'Stock')} · {fmt_price(row.get('live_price'))} · intraday score {row.get('live_score', '—')}/100"):
                st.write(f"**Decision:** {row.get('live_status', 'WAIT')} · **Risk:** {row.get('risk', 'Unknown')}")
                st.write(f"**Last completed 5m candle:** {row.get('live_quote_time', 'n/a')} · **Age:** {row.get('live_quote_age_seconds', 'n/a')} seconds")
                st.write("**Reference levels only — not live exchange quotes or orders**")
                a, b, c, d = st.columns(4)
                a.metric("Entry zone", f"{fmt_price(row.get('live_entry_low'))} – {fmt_price(row.get('live_entry_high'))}")
                b.metric("Stop reference", fmt_price(row.get("live_stop")))
                c.metric("Target 1", fmt_price(row.get("live_target1")))
                d.metric("Target 2", fmt_price(row.get("live_target2")))
                st.write("**Why it passed / what is missing**")
                st.write(row.get("live_reason", "No additional explanation"))
                flags = row.get("flags", [])
                if isinstance(flags, list):
                    for flag in flags:
                        st.warning(flag)
                news = row.get("news", [])
                if isinstance(news, list):
                    for headline in news:
                        title_text = str(headline.get("title", "News"))
                        link = str(headline.get("link", ""))
                        published = headline.get("published", "date n/a")
                        if link.startswith(("https://", "http://")):
                            st.markdown(f"- [{title_text}]({link}) · {published}")
                        else:
                            st.write(f"- {title_text} · {published}")

    # Always keep delivery / swing research visible, even when the market is closed
    # or intraday data is unavailable. Intraday confirmation is a separate layer.
    delivery_count = len(delivery_low) + len(delivery_high)
    live_count = int(result.get("live_confirmed_count", len(low_live) + len(high_live)) or 0)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Daily candidates", int(result.get("candidate_count", delivery_count) or 0))
    m2.metric("Delivery shortlist", delivery_count)
    m3.metric("Intraday confirmed", live_count)
    m4.metric("Daily histories", f"{int(result.get('success_count', 0) or 0)}/{int(result.get('selected_count', 0) or 0)}")
    m5.metric("Nifty regime", str(market.get("regime", "n/a")).upper())

    st.caption(
        f"Last scan: {st.session_state.get('scan_completed_at', 'time unavailable')} · "
        f"Daily baseline: {result.get('data_date', 'n/a')} · "
        f"Universe: {int(result.get('universe_count', 0) or 0):,} securities · "
        f"Scored: {int(result.get('scored_count', 0) or 0):,}"
    )

    if session.get("phase") != "open":
        st.info(format_market_status(session))
    elif not result.get("live_ready", False):
        st.warning(result.get("live_error", "Intraday data is unavailable. Daily delivery research remains available below."))
    else:
        age = result.get("live_candle_age_seconds")
        st.success(
            f"Intraday check completed · {result.get('live_provider', 'provider n/a')} · "
            f"Nifty candle age: {age if age is not None else 'n/a'} sec · "
            f"Coverage: {result.get('live_coverage_pct', 0):.1f}%"
        )

    overview_tab, delivery_tab, intraday_tab, market_tab, ledger_tab = st.tabs(
        ["📊 Overview", "📦 Delivery & Swing", "⚡ Intraday", "🌍 Market & News", "📒 Performance"]
    )

    with overview_tab:
        left, right = st.columns([1.2, 1])
        with left:
            st.subheader("Market snapshot")
            a, b, c = st.columns(3)
            a.metric("Nifty 1D", fmt_pct(market.get("nifty_change_1d")))
            b.metric("Nifty 5D", fmt_pct(market.get("nifty_change_5d")))
            c.metric("Global risk", str(market.get("global_risk", "unknown")).replace("_", " ").upper())
            st.caption(f"Market context date: {market.get('data_date', 'n/a')} · Global breadth: {market.get('global_positive_count', 0)}/{market.get('global_count', 0)} positive")
            breadth = result.get("live_breadth") or {}
            if breadth:
                st.write("**Researched intraday shortlist breadth**")
                x, y, z = st.columns(3)
                x.metric("Advances", breadth.get("advances", 0))
                y.metric("Declines", breadth.get("declines", 0))
                z.metric("Unchanged", breadth.get("unchanged", 0))
                st.caption("Breadth covers only the researched shortlist, not the full exchange.")
        with right:
            st.subheader("Scan coverage")
            coverage_data = {
                "Stage": ["Selected", "Daily history", "Scored", "Eligible"],
                "Stocks": [
                    int(result.get("selected_count", 0) or 0),
                    int(result.get("success_count", 0) or 0),
                    int(result.get("scored_count", 0) or 0),
                    int(result.get("candidate_count", 0) or 0),
                ],
            }
            coverage_fig = px.bar(
                pd.DataFrame(coverage_data),
                x="Stocks",
                y="Stage",
                orientation="h",
                text="Stocks",
                title="Universe-to-candidate funnel",
            )
            coverage_fig.update_layout(height=260, margin=dict(l=5, r=5, t=45, b=5), showlegend=False)
            st.plotly_chart(coverage_fig, use_container_width=True, config={"displayModeBar": False})

        daily_top = pd.concat([delivery_low, delivery_high], ignore_index=True)
        if not daily_top.empty and "score" in daily_top:
            chart_data = daily_top.sort_values("score", ascending=True).copy()
            chart_data["label"] = chart_data["symbol"].astype(str) + " · " + chart_data["exchange"].astype(str)
            score_fig = px.bar(
                chart_data,
                x="score",
                y="label",
                color="score",
                orientation="h",
                text="score",
                hover_data=["company", "price", "risk"],
                title="Top delivery / swing candidates",
                range_x=[0, 100],
            )
            score_fig.update_layout(height=max(280, 42 * len(chart_data)), margin=dict(l=5, r=5, t=45, b=5), coloraxis_showscale=False)
            st.plotly_chart(score_fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No delivery / swing candidates met the configured score and risk filters.")

    with delivery_tab:
        st.caption("Daily-candle research can run before or after market hours. These are watchlists, not automatic buy signals.")
        col_a, col_b = st.columns(2)
        with col_a:
            render_delivery_bucket("🟢 Price ≤ ₹1,000", delivery_low)
        with col_b:
            render_delivery_bucket("🔵 Price > ₹1,000", delivery_high)

    with intraday_tab:
        st.caption("Only completed 5-minute candles that pass freshness, continuity, VWAP, momentum, volume and market-alignment checks can appear as confirmed.")
        if not result.get("live_ready", False):
            st.info(result.get("live_error", "Intraday confirmation is unavailable for this scan."))
        else:
            st.metric("Nifty latest completed 5m move", fmt_pct(result.get("live_nifty_change_pct")))
            col_a, col_b = st.columns(2)
            with col_a:
                render_live_bucket("🟢 Confirmed · Latest close ≤ ₹1,000", low_live)
            with col_b:
                render_live_bucket("🔵 Confirmed · Latest close > ₹1,000", high_live)
            gap_up = as_frame(result.get("gap_up"))
            gap_down = as_frame(result.get("gap_down"))
            if not gap_up.empty or not gap_down.empty:
                st.divider()
                st.subheader("Observed opening-gap watchlists")
                ga, gb = st.columns(2)
                with ga:
                    st.write("**Gap-up ≥ +0.50%**")
                    render_stock_table(gap_up, "live")
                with gb:
                    st.write("**Gap-down ≤ −0.50%**")
                    render_stock_table(gap_down, "live")

    with market_tab:
        st.subheader("Benchmark monitor")
        benchmarks = market.get("benchmarks") or {}
        if benchmarks:
            rows = []
            for name, values in benchmarks.items():
                rows.append({
                    "Benchmark": name.replace("_", " "),
                    "1D": fmt_pct(values.get("daily_pct")),
                    "1W": fmt_pct(values.get("weekly_pct")),
                    "1M": fmt_pct(values.get("monthly_pct")),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Benchmark history is unavailable in this scan.")
        st.divider()
        st.subheader("Global headlines")
        global_news = result.get("global_news") or []
        if not global_news:
            st.info("No global headlines were returned.")
        for item in global_news:
            title_text = str(item.get("title", "Headline"))
            link = str(item.get("link", ""))
            meta = f"{item.get('source', 'Source n/a')} · {item.get('published', 'date n/a')}"
            if link.startswith(("https://", "http://")):
                st.markdown(f"- [{title_text}]({link})  \n  <span class='radar-muted'>{meta}</span>", unsafe_allow_html=True)
            else:
                st.write(f"- {title_text} · {meta}")
        st.divider()
        st.subheader("Official / regulatory headlines")
        official_news = result.get("official_news") or []
        if not official_news:
            st.info("No official headlines were returned.")
        for item in official_news:
            title_text = str(item.get("title", "Official update"))
            link = str(item.get("link", ""))
            meta = f"{item.get('source', 'Source n/a')} · {item.get('published', 'date n/a')}"
            if link.startswith(("https://", "http://")):
                st.markdown(f"- [{title_text}]({link})  \n  <span class='radar-muted'>{meta}</span>", unsafe_allow_html=True)
            else:
                st.write(f"- {title_text} · {meta}")
        st.caption(
            f"News items: {result.get('news_count', 0)} · "
            f"Working sources: {result.get('news_sources_working', 0)}/{result.get('news_sources_total', 0)}"
        )
        source_status = result.get("news_source_status") or {}
        if source_status:
            with st.expander("News source health"):
                st.json(source_status)

    with ledger_tab:
        st.subheader("Forward-test performance")
        ledger_frame = read_ledger()
        if ledger_frame.empty:
            st.info("No forward-test picks have been logged yet. Picks are recorded after a qualifying scan.")
        else:
            for column in ("return_5d_pct", "return_20d_pct"):
                if column not in ledger_frame:
                    ledger_frame[column] = pd.NA
            ret5 = pd.to_numeric(ledger_frame["return_5d_pct"], errors="coerce").dropna()
            ret20 = pd.to_numeric(ledger_frame["return_20d_pct"], errors="coerce").dropna()
            a, b, c, d = st.columns(4)
            a.metric("Logged picks", len(ledger_frame))
            b.metric("5-session observations", len(ret5))
            c.metric("5D positive outcomes", f"{(ret5 > 0).mean() * 100:.1f}%" if not ret5.empty else "n/a")
            d.metric("20-session observations", len(ret20))
            if not ret5.empty or not ret20.empty:
                chart_rows = []
                if not ret5.empty:
                    chart_rows.append({"Horizon": "5 sessions", "Average return %": ret5.mean(), "Observations": len(ret5)})
                if not ret20.empty:
                    chart_rows.append({"Horizon": "20 sessions", "Average return %": ret20.mean(), "Observations": len(ret20)})
                perf_fig = px.bar(
                    pd.DataFrame(chart_rows),
                    x="Horizon",
                    y="Average return %",
                    color="Average return %",
                    hover_data=["Observations"],
                    title="Average observed forward return",
                )
                perf_fig.add_hline(y=0, line_dash="dash")
                perf_fig.update_layout(height=300, margin=dict(l=5, r=5, t=45, b=5), coloraxis_showscale=False)
                st.plotly_chart(perf_fig, use_container_width=True, config={"displayModeBar": False})
            ledger_display = ledger_frame.copy()
            for col in ("price", "live_price"):
                if col in ledger_display:
                    ledger_display[col] = ledger_display[col].map(fmt_price)
            for col in ("return_5d_pct", "return_20d_pct"):
                if col in ledger_display:
                    ledger_display[col] = ledger_display[col].map(fmt_pct)
            st.dataframe(
                ledger_display.sort_values("asof_date", ascending=False).head(200),
                use_container_width=True,
                hide_index=True,
            )
            st.caption("Forward returns use the recorded entry basis (daily close for legacy rows; latest completed 5m close where captured). Different entry bases should not be compared without adjustment.")

st.divider()
st.caption(
    "Model scores are heuristic rankings, not calibrated probabilities of profit. "
    "Data limitations: no complete audited-fundamentals feed, official delivery-volume history, full FII/DII flows, "
    "institutional order-book data or full exchange-filings parser is integrated. "
    "Verify all prices, liquidity, news and risk independently before placing any order."
)
