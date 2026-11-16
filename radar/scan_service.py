"""Reusable zero-cost scanner for Telegram commands and the optional dashboard.

Live session is determined locally first. Stock ranking uses completed daily
Yahoo candles; intraday confirmation uses the latest completed Yahoo 5-minute
bars for both NSE (.NS) and BSE (.BO) symbols.

Yahoo is unofficial and may be delayed. This module never calls broker order
APIs and never claims a Yahoo candle close is an exchange live last-traded price.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from datetime import datetime, timedelta, timezone

from radar.free_data import (
    fetch_many,
    fetch_market_context,
    fetch_daily_history,
    fetch_intraday_5m_snapshot,
    YAHOO_INTRADAY_PROVIDER,
)
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
    read_refresh_status,
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


def _cache_needs_refresh(exchange, max_age_days=7):
    """Treat unknown or older-than-seven-day cache metadata as stale."""
    metadata = read_refresh_status().get(exchange, {})
    updated = metadata.get("updated_at_utc") if isinstance(metadata, dict) else None
    if not updated:
        return True
    try:
        stamp = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)
        return age < timedelta(minutes=-5) or age > timedelta(days=max_age_days)
    except (TypeError, ValueError):
        return True


def ensure_exchange_universes():
    """Refresh stale exchange caches independently; preserve usable old cache on failure."""
    errors = {}
    for exchange, loader in (("nse", load_cached_nse_universe), ("bse", load_cached_bse_universe)):
        try:
            cached = loader()
        except Exception as exc:
            cached = pd.DataFrame()
            errors[f"{exchange}_cache"] = str(exc)
        if cached.empty or _cache_needs_refresh(exchange):
            try:
                refresh_exchange(exchange)
            except Exception as exc:
                errors[exchange] = str(exc)
                # Keep a valid older cache if present, but report that it is stale.
    nse = load_cached_nse_universe()
    bse = load_cached_bse_universe()
    universe = load_cached_combined_universe()
    if errors and universe.empty:
        errors["combined"] = "No valid cached securities remained after refresh failures."
    return universe, errors


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
    """Remove the current day's unfinished daily bar before daily scoring."""
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


def _free_intraday_one(meta, now, session_open):
    """Fetch one candidate's latest completed 5-minute Yahoo candles."""
    symbol = str(meta.get("yahoo_symbol", "")).strip()
    if not symbol:
        return None
    result = fetch_intraday_5m_snapshot(symbol, now=now, session_open=session_open)
    if not result:
        return None
    return result


def run_scan(limit=250, min_score=60, news_limit=6, workers=6):
    """Run a market-open scan using free, timestamp-labelled market data."""
    limit = int(limit)
    if limit not in (250, 500):
        raise ValueError("Choose 250 or 500")

    # Intraday signals are session-gated; daily delivery research can run
    # outside market hours using completed daily candles only.
    market_session = get_market_status()
    delivery_only = market_session.get("phase") != "open"

    universe, universe_refresh_errors = ensure_exchange_universes()
    if universe.empty:
        return _empty_result(
            market_session,
            f"No exchange universe is available. Refresh errors: {universe_refresh_errors}",
        )

    bse_universe_count = len(load_cached_bse_universe())
    nse_universe_count = len(load_cached_nse_universe())
    nse_refresh_error = universe_refresh_errors.get("nse")
    bse_refresh_error = universe_refresh_errors.get("bse")

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
            histories[f"{str(meta.get('exchange', '')).upper()}:{str(meta.get('symbol', ''))}"] = completed
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

    try:
        news_bundle = fetch_market_news()
    except Exception:
        news_bundle = {
            "items": [], "total_items": 0, "working_sources": 0,
            "total_sources": 0, "source_status": {}, "global_news": [],
            "official_news": [],
        }

    # Run company-specific RSS lookups only for the leaders from the daily model.
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

    # Delivery candidates use completed daily data and do not depend on 5m confirmation.
    delivery_low = daily_eligible[daily_eligible["price"] <= 1000].sort_values(
        "score", ascending=False
    ).head(5).reset_index(drop=True)
    delivery_high = daily_eligible[daily_eligible["price"] > 1000].sort_values(
        "score", ascending=False
    ).head(5).reset_index(drop=True)
    delivery_picks = pd.concat([delivery_low, delivery_high], ignore_index=True)
    if not delivery_picks.empty:
        save_daily_picks(delivery_picks, histories, market["regime"])

    delivery_meta = {
        "market": market,
        "universe_count": len(universe),
        "selected_count": len(selected),
        "success_count": len(downloaded),
        "scored_count": len(base),
        "candidate_count": len(daily_eligible),
        "excluded_count": int((~base["eligible"].astype(bool)).sum()),
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
        "nse_universe_count": nse_universe_count,
        "bse_universe_count": bse_universe_count,
        "nse_refresh_error": nse_refresh_error,
        "bse_refresh_error": bse_refresh_error,
        "delivery_low": delivery_low,
        "delivery_high": delivery_high,
        "delivery_only": delivery_only,
    }

    if delivery_only:
        return {
            "market_session": market_session,
            "live_ready": False,
            "live_error": "Market is closed; intraday confirmation is intentionally disabled.",
            **delivery_meta,
        }

    # Select up to 18 daily leaders in each close-price band before downloading
    # intraday data. The final band is determined from the latest 5m close.
    low_pre = daily_eligible[daily_eligible["price"] <= 1000].sort_values(
        "score", ascending=False
    ).head(18)
    high_pre = daily_eligible[daily_eligible["price"] > 1000].sort_values(
        "score", ascending=False
    ).head(18)
    detailed = pd.concat([low_pre, high_pre]).drop_duplicates(["exchange", "symbol"])

    # Yahoo's public 5m chart feed is the zero-cost option. Use the Yahoo
    # ticker (.NS or .BO) provided by each exchange's universe mapping.
    current = pd.Timestamp.now(tz="Asia/Kolkata").to_pydatetime()
    session_open = market_session.get("session_open") or "09:15"
    intraday_results = {}
    detail_failures = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_free_intraday_one, row.to_dict(), current, session_open): index
            for index, row in detailed.iterrows()
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                intraday_results[index] = future.result()
            except Exception:
                intraday_results[index] = None
                detail_failures += 1

    # Nifty 5m feed gives a same-provider broad-market comparator.
    nifty_intraday = fetch_intraday_5m_snapshot("^NSEI", now=current, session_open=session_open)
    if not nifty_intraday:
        return _empty_result(
            market_session,
            "Free intraday Nifty 5-minute data is unavailable. No recommendations were generated.",
            live_provider=YAHOO_INTRADAY_PROVIDER,
            market=market,
            universe_count=len(universe),
            selected_count=len(selected),
            success_count=len(downloaded),
            **delivery_meta,
        )

    nifty_prev_close = _previous_nifty_close(session_date)
    if not nifty_prev_close or nifty_prev_close <= 0:
        return _empty_result(
            market_session,
            "Could not determine previous completed Nifty close; relative-strength check is unavailable.",
            live_provider=YAHOO_INTRADAY_PROVIDER,
            market=market,
            **delivery_meta,
        )

    nifty_candle_price = float(nifty_intraday["snapshot"]["price"])
    nifty_change = (nifty_candle_price / nifty_prev_close - 1.0) * 100.0
    nifty_candle_age = nifty_intraday["detail"]["age_seconds"]
    nifty_candle_end = nifty_intraday["snapshot"]["bar_end_at"]
    if nifty_candle_age > 600:
        return _empty_result(
            market_session,
            "Latest completed Nifty 5-minute candle is older than 10 minutes. No recommendations were generated.",
            live_provider=YAHOO_INTRADAY_PROVIDER,
            market=market,
        )

    live_rows = []
    for index, row in detailed.iterrows():
        intraday = intraday_results.get(index)
        if not intraday:
            continue
        signal = build_live_signal(
            row,
            intraday["snapshot"],
            intraday["detail"],
            nifty_change_pct=nifty_change,
            nifty_candle_end_time=nifty_candle_end,
        )
        live_rows.append(_merge_live(row, signal))

    live_frame = pd.DataFrame(live_rows)
    if live_frame.empty:
        low = pd.DataFrame()
        high = pd.DataFrame()
    else:
        confirmed = live_frame[live_frame["live_eligible"] == True].copy()
        low = confirmed[confirmed["live_price"] <= 1000].sort_values(
            ["live_score", "score"], ascending=False
        ).head(5).reset_index(drop=True)
        high = confirmed[confirmed["live_price"] > 1000].sort_values(
            ["live_score", "score"], ascending=False
        ).head(5).reset_index(drop=True)

    confirmed_picks = pd.concat([low, high], ignore_index=True)
    if not confirmed_picks.empty:
        # Persist selected daily baselines for later performance tracking.
        save_daily_picks(confirmed_picks, histories, market["regime"])

    nse_count = int((selected["exchange"].astype(str).str.upper() == "NSE").sum())
    bse_count = int((selected["exchange"].astype(str).str.upper() == "BSE").sum())
    expected_intraday = len(detailed)
    successful_intraday = sum(value is not None for value in intraday_results.values())
    coverage = 100.0 * successful_intraday / expected_intraday if expected_intraday else 0.0
    shortlist_changes = [
        float(item.get("live_change_pct"))
        for item in live_rows
        if item.get("live_change_pct") is not None
    ]
    breadth_advances = sum(value > 0.05 for value in shortlist_changes)
    breadth_declines = sum(value < -0.05 for value in shortlist_changes)
    breadth_unchanged = len(shortlist_changes) - breadth_advances - breadth_declines

    return {
        "market_session": market_session,
        "live_ready": True,
        "live_provider": YAHOO_INTRADAY_PROVIDER,
        "live_price_type": "latest completed 5-minute candle close; not exchange LTP",
        "live_checked_at": current.isoformat(timespec="seconds"),
        "live_candle_age_seconds": round(nifty_candle_age, 1),
        "live_coverage_pct": round(coverage, 1),
        "live_coverage_count": successful_intraday,
        "live_coverage_total": expected_intraday,
        "live_nifty_price": round(nifty_candle_price, 2),
        "live_nifty_change_pct": round(nifty_change, 2),
        "live_breadth": {
            "advances": breadth_advances,
            "declines": breadth_declines,
            "unchanged": breadth_unchanged,
            "stocks_with_live_quotes": len(shortlist_changes),
            "scope": "researched shortlist only",
        },
        "live_researched_count": len(live_frame),
        "live_confirmed_count": len(confirmed_picks),
        "live_wait_count": int((live_frame["live_eligible"] == False).sum()) if not live_frame.empty else 0,
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
        "nse_selected": nse_count,
        "bse_selected": bse_count,
        "nse_universe_count": nse_universe_count,
        "bse_universe_count": bse_universe_count,
        "nse_refresh_error": nse_refresh_error,
        "bse_refresh_error": bse_refresh_error,
        "bse_live_supported": True,
        "delivery_low": delivery_low,
        "delivery_high": delivery_high,
        "delivery_only": False,
        "delivery_candidate_count": len(delivery_picks),
    }
