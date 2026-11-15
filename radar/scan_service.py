"""Reusable scanner shared by Telegram commands and the optional Streamlit dashboard.

The Telegram scan path is live-only:
1) Verify the NSE cash session is open.
2) Require Groww live-data credentials.
3) Rank completed daily candles (never today's unfinished Yahoo candle).
4) Confirm leading stocks using live LTP/OHLC and completed 5-minute candles.
5) Return only candidates that pass intraday confirmation; otherwise NO TRADE.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

from radar.free_data import fetch_many, fetch_market_context, fetch_daily_history
from radar.groww_live import GrowwLiveClient, LiveDataUnavailable, fetch_live_snapshots, fetch_candidate_detail
from radar.ledger import save_daily_picks
from radar.live_signals import build_live_signal
from radar.market_clock import get_market_status
from radar.news import company_news, fetch_market_news
from radar.scoring import apply_news_overlay, score_stock
from radar.universe import (
    fetch_bse_universe,
    fetch_nse_universe,
    load_cached_combined_universe,
    load_cached_nse_universe,
    load_cached_bse_universe,
    select_scan_universe,
)


def refresh_exchange(exchange):
    exchange = str(exchange).strip().lower()
    if exchange == "nse":
        frame = fetch_nse_universe()
    elif exchange == "bse":
        frame = fetch_bse_universe()
    else:
        raise ValueError("Exchange must be NSE or BSE")
    return {"exchange": exchange.upper(), "count": len(frame)}


def refresh_both():
    results, errors = {}, {}
    for exchange in ("nse", "bse"):
        try:
            results[exchange] = refresh_exchange(exchange)
        except Exception as exc:
            errors[exchange] = str(exc)
    return {"refreshed": results, "errors": errors}


def universe_status():
    return {
        "nse": len(load_cached_nse_universe()),
        "bse": len(load_cached_bse_universe()),
        "combined": len(load_cached_combined_universe()),
    }


def _empty_result(market_session, message, **extra):
    return {
        "market_session": market_session,
        "live_ready": False,
        "live_error": message,
        "low": pd.DataFrame(),
        "high": pd.DataFrame(),
        **extra,
    }


def _completed_history(history, session_date):
    """Remove the current day's still-forming daily bar before daily scoring."""
    if history is None or history.empty:
        return pd.DataFrame()
    index = pd.to_datetime(history.index)
    keep = [stamp.date() < session_date for stamp in index]
    return history.loc[keep].copy()


def _previous_nifty_close(session_date):
    history = fetch_daily_history("^NSEI", period="1mo")
    completed = _completed_history(history, session_date)
    if completed.empty:
        return None
    return float(completed["Close"].iloc[-1])


def _merge_live(row, signal):
    merged = row.to_dict()
    merged.update(signal)
    return merged


def run_scan(limit=250, min_score=60, news_limit=6, workers=6):
    """Run a market-open scan and require live intraday confirmation."""
    limit = int(limit)
    if limit not in (250, 500):
        raise ValueError("Choose 250 or 500")

    # Market-session gate is deliberately first: no stock scan on a holiday,
    # weekend, pre-open, post-close or an unconfigured calendar year.
    market_session = get_market_status()
    if market_session.get("phase") != "open":
        return _empty_result(
            market_session,
            "The NSE regular cash market is not open. No stock scan was run.",
        )

    # Do not silently fall back to Yahoo daily closes for live recommendations.
    try:
        client = GrowwLiveClient()
    except LiveDataUnavailable as exc:
        return _empty_result(
            market_session,
            str(exc),
            live_provider="Groww Live Data API",
            live_coverage_pct=0.0,
        )

    universe = load_cached_combined_universe()
    if universe.empty:
        refresh_result = refresh_both()
        universe = load_cached_combined_universe()
        if universe.empty:
            return _empty_result(
                market_session,
                f"No exchange universe is available. Refresh errors: {refresh_result['errors']}",
            )

    selected = select_scan_universe(universe, limit)
    if selected.empty:
        return _empty_result(market_session, "The cached exchange universe is empty.")

    session_date = pd.Timestamp(market_session["local_date"]).date()
    downloaded = fetch_many(selected, workers=workers)
    market = fetch_market_context()

    results, histories = [], {}
    for meta, history in downloaded:
        try:
            completed = _completed_history(history, session_date)
            if len(completed) < 61:
                continue
            scored = score_stock(meta, completed, market)
            results.append({**meta, **scored})
            histories[str(meta.get("symbol", ""))] = completed
        except Exception:
            continue

    base = pd.DataFrame(results)
    if base.empty:
        return _empty_result(market_session, "No usable completed daily price histories were returned.")

    base["news"] = pd.Series([[] for _ in range(len(base))], index=base.index, dtype="object")
    base["news_score"] = pd.NA
    base["news_adjustment"] = 0.0
    base["news_flags"] = pd.Series([[] for _ in range(len(base))], index=base.index, dtype="object")

    # Broad official/global news feeds are queried once; company research is
    # bounded to the leading preliminary names to control runtime and RSS load.
    try:
        news_bundle = fetch_market_news()
    except Exception:
        news_bundle = {
            "items": [], "total_items": 0, "working_sources": 0,
            "total_sources": 0, "source_status": {}, "global_news": [],
            "official_news": [],
        }

    shortlist = base.sort_values("score", ascending=False).head(35)

    def fetch_candidate_news(index, row):
        try:
            headlines = company_news(
                row.get("company", row.get("symbol", "")),
                limit=news_limit,
                official_items=news_bundle["items"],
                symbol=row.get("symbol", ""),
            )
        except Exception:
            headlines = []
        return index, headlines

    news_results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [
            pool.submit(fetch_candidate_news, index, row)
            for index, row in shortlist.iterrows()
        ]
        for future in as_completed(futures):
            try:
                news_results.append(future.result())
            except Exception:
                continue

    for index, headlines in news_results:
        adjusted, news_score, adjustment, news_flags = apply_news_overlay(
            float(base.at[index, "base_score"]), headlines
        )
        base.at[index, "score"] = adjusted
        base.at[index, "news_score"] = news_score
        base.at[index, "news_adjustment"] = adjustment
        base.at[index, "news_flags"] = news_flags
        base.at[index, "news"] = headlines

    daily_eligible = base[
        (base["eligible"] == True)
        & (base["score"] >= float(min_score))
        & (base["setup_status"] == "Watchlist candidate")
    ].copy()

    # Groww requires exchange trading symbols. The current BSE cache stores
    # BSE scrip codes, not Groww trading symbols; don't pass those codes as
    # symbols. NSE instruments are live-screened until BSE mapping is verified.
    nse_selected = selected[
        selected["exchange"].astype(str).str.upper().eq("NSE")
    ].copy()
    nse_selected = nse_selected.drop_duplicates("symbol")
    instruments = [
        {"exchange": "NSE", "symbol": str(symbol)}
        for symbol in nse_selected["symbol"].tolist()
    ]
    instruments.append({"exchange": "NSE", "symbol": "NIFTY"})

    try:
        snapshots = fetch_live_snapshots(client, instruments)
    except LiveDataUnavailable as exc:
        return _empty_result(
            market_session,
            f"Groww live-data request failed: {exc}",
            live_provider="Groww Live Data API",
            market=market,
            universe_count=len(universe),
            selected_count=len(selected),
            success_count=len(downloaded),
        )

    stock_snapshot_count = sum(
        1 for symbol in nse_selected["symbol"].astype(str)
        if f"NSE_{symbol.upper()}" in snapshots
    )
    live_coverage = stock_snapshot_count / len(nse_selected) if len(nse_selected) else 0.0
    if live_coverage < 0.70:
        return _empty_result(
            market_session,
            "Groww live quote coverage is below 70%; no live recommendations were generated.",
            live_provider="Groww Live Data API",
            live_coverage_pct=round(live_coverage * 100, 1),
            live_coverage_count=stock_snapshot_count,
            live_coverage_total=len(nse_selected),
            market=market,
            universe_count=len(universe),
            selected_count=len(selected),
            success_count=len(downloaded),
        )

    nifty_snapshot = snapshots.get("NSE_NIFTY")
    if not nifty_snapshot:
        return _empty_result(
            market_session,
            "Groww did not return a live Nifty quote; broad-market confirmation is unavailable.",
            live_provider="Groww Live Data API",
            live_coverage_pct=round(live_coverage * 100, 1),
            live_coverage_count=stock_snapshot_count,
            live_coverage_total=len(nse_selected),
            market=market,
        )

    nifty_prev_close = _previous_nifty_close(session_date)
    if not nifty_prev_close or nifty_prev_close <= 0:
        return _empty_result(
            market_session,
            "Could not determine the previous completed Nifty close; live relative-strength checks are blocked.",
            live_provider="Groww Live Data API",
            live_coverage_pct=round(live_coverage * 100, 1),
            market=market,
        )
    nifty_live_change = (float(nifty_snapshot["price"]) / nifty_prev_close - 1.0) * 100.0

    # Breadth is calculated from current live LTPs versus each stock's last
    # completed daily close, not from Yahoo's possibly unfinished current bar.
    advances = declines = unchanged = 0
    breadth_changes = []
    for _, row in base.iterrows():
        if str(row.get("exchange", "")).upper() != "NSE":
            continue
        snap = snapshots.get(f"NSE_{str(row.get('symbol', '')).upper()}")
        previous = float(row.get("price", 0) or 0)
        if not snap or previous <= 0:
            continue
        change = (float(snap["price"]) / previous - 1.0) * 100.0
        breadth_changes.append(change)
        if change > 0.05:
            advances += 1
        elif change < -0.05:
            declines += 1
        else:
            unchanged += 1

    # Research no more than 18 leaders in each previous-close price band.
    # Live price decides the final price band in the returned recommendations.
    low_pre = daily_eligible[daily_eligible["price"] <= 1000].sort_values("score", ascending=False).head(18)
    high_pre = daily_eligible[daily_eligible["price"] > 1000].sort_values("score", ascending=False).head(18)
    detailed = pd.concat([low_pre, high_pre]).drop_duplicates("symbol")
    live_rows = []
    detail_failures = 0
    for _, row in detailed.iterrows():
        if str(row.get("exchange", "")).upper() != "NSE":
            detail_failures += 1
            continue
        symbol = str(row.get("symbol", "")).upper()
        snapshot = snapshots.get(f"NSE_{symbol}")
        if not snapshot:
            detail_failures += 1
            continue
        try:
            detail = fetch_candidate_detail(client, symbol, exchange="NSE")
            signal = build_live_signal(
                row,
                snapshot,
                detail,
                nifty_change_pct=nifty_live_change,
            )
            live_rows.append(_merge_live(row, signal))
        except Exception:
            detail_failures += 1
            continue

    live_frame = pd.DataFrame(live_rows)
    if live_frame.empty:
        low = pd.DataFrame()
        high = pd.DataFrame()
    else:
        confirmed = live_frame[live_frame["live_eligible"] == True].copy()
        confirmed["price_band"] = confirmed["live_price"].apply(
            lambda price: "≤ ₹1,000" if float(price) <= 1000 else "> ₹1,000"
        )
        low = confirmed[confirmed["live_price"] <= 1000].sort_values(
            ["live_score", "score"], ascending=False
        ).head(5).reset_index(drop=True)
        high = confirmed[confirmed["live_price"] > 1000].sort_values(
            ["live_score", "score"], ascending=False
        ).head(5).reset_index(drop=True)

    confirmed_picks = pd.concat([low, high], ignore_index=True)
    if not confirmed_picks.empty:
        # Save only stocks that passed today's live confirmation. Price field
        # remains the last completed daily close for forward-return accounting.
        save_daily_picks(confirmed_picks, histories, market["regime"])

    return {
        "market_session": market_session,
        "live_ready": True,
        "live_provider": "Groww Live Data API",
        "live_checked_at": market_session.get("checked_at"),
        "live_coverage_pct": round(live_coverage * 100, 1),
        "live_coverage_count": stock_snapshot_count,
        "live_coverage_total": len(nse_selected),
        "live_nifty_price": round(float(nifty_snapshot["price"]), 2),
        "live_nifty_change_pct": round(nifty_live_change, 2),
        "live_breadth": {
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "stocks_with_live_quotes": len(breadth_changes),
        },
        "live_researched_count": len(live_frame),
        "live_confirmed_count": len(confirmed_picks),
        "live_wait_count": int(
            (live_frame["live_eligible"] == False).sum()
        ) if not live_frame.empty else 0,
        "live_detail_failures": detail_failures,
        "limit": limit,
        "market": market,
        "universe_count": len(universe),
        "selected_count": len(selected),
        "success_count": len(downloaded),
        "scored_count": len(base),
        "candidate_count": len(daily_eligible),
        "excluded_count": int((~base["eligible"].astype(bool)).sum()),
        "low": low,
        "high": high,
        "data_date": str(base["data_date"].max()),
        "news_count": news_bundle["total_items"],
        "news_sources_working": news_bundle["working_sources"],
        "news_sources_total": news_bundle["total_sources"],
        "news_source_status": news_bundle["source_status"],
        "global_news": news_bundle["global_news"][:6],
        "official_news": news_bundle["official_news"][:10],
        "benchmarks": market.get("benchmarks", {}),
        "nse_selected": int((selected["exchange"].astype(str).str.upper() == "NSE").sum()),
        "bse_selected": int((selected["exchange"].astype(str).str.upper() == "BSE").sum()),
        "bse_live_supported": False,
    }
