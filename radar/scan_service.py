"""Reusable scanner used by both Streamlit UI and the Telegram command worker."""
import pandas as pd

from radar.free_data import fetch_many, fetch_nifty, market_context
from radar.ledger import save_daily_picks
from radar.news import company_news
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
    results = {}
    errors = {}
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


def run_scan(limit=250, min_score=60, news_limit=6, workers=6):
    """Run the full daily-close scan and return two top-five frames and metadata."""
    limit = int(limit)
    if limit not in (250, 500):
        raise ValueError("Choose 250 or 500 stocks")

    universe = load_cached_combined_universe()
    if universe.empty:
        result = refresh_both()
        universe = load_cached_combined_universe()
        if universe.empty:
            raise RuntimeError(f"No exchange universe is available. Refresh errors: {result['errors']}")

    selected = select_scan_universe(universe, limit)
    if selected.empty:
        raise RuntimeError("The cached exchange universe is empty")
    downloaded = fetch_many(selected, workers=workers)
    market = market_context(fetch_nifty())

    results = []
    histories = {}
    for meta, history in downloaded:
        try:
            scored = score_stock(meta, history, market)
            results.append({**meta, **scored})
            histories[str(meta.get("symbol", ""))] = history
        except Exception:
            continue

    base = pd.DataFrame(results)
    if base.empty:
        raise RuntimeError("Yahoo Finance returned no usable daily histories for this scan")

    base["news"] = pd.Series([[] for _ in range(len(base))], index=base.index, dtype="object")
    base["news_score"] = pd.NA
    base["news_adjustment"] = 0.0
    shortlist = base.sort_values("score", ascending=False).head(30)
    for index, row in shortlist.iterrows():
        try:
            headlines = company_news(row.get("company", row.get("symbol", "")), limit=news_limit)
        except Exception:
            headlines = []
        adjusted, news_score, adjustment = apply_news_overlay(float(row["base_score"]), headlines)
        base.at[index, "score"] = adjusted
        base.at[index, "news_score"] = news_score
        base.at[index, "news_adjustment"] = adjustment
        base.at[index, "news"] = headlines

    eligible = base[
        (base["eligible"] == True)
        & (base["score"] >= float(min_score))
        & (base["setup_status"] == "Watchlist candidate")
    ].copy()
    low = eligible[eligible["price"] <= 1000].sort_values("score", ascending=False).head(5).reset_index(drop=True)
    high = eligible[eligible["price"] > 1000].sort_values("score", ascending=False).head(5).reset_index(drop=True)
    picked = pd.concat([low, high], ignore_index=True)
    if not picked.empty:
        save_daily_picks(picked, histories, market["regime"])

    return {
        "limit": limit,
        "market": market,
        "universe_count": len(universe),
        "selected_count": len(selected),
        "success_count": len(downloaded),
        "scored_count": len(base),
        "candidate_count": len(eligible),
        "excluded_count": int((~base["eligible"].astype(bool)).sum()),
        "low": low,
        "high": high,
        "data_date": market.get("data_date") or str(base["data_date"].max()),
    }
