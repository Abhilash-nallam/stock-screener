"""Reusable scanner shared by Telegram commands and the optional Streamlit dashboard."""
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from radar.free_data import fetch_many, fetch_market_context
from radar.ledger import save_daily_picks
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


def run_scan(limit=250, min_score=60, news_limit=6, workers=6):
    """Scan a daily rotating sample and return transparent ranked candidates."""
    limit = int(limit)
    if limit not in (250, 500):
        raise ValueError("Choose 250 or 500 stocks")

    universe = load_cached_combined_universe()
    if universe.empty:
        refresh_result = refresh_both()
        universe = load_cached_combined_universe()
        if universe.empty:
            raise RuntimeError(f"No exchange universe is available. Refresh errors: {refresh_result['errors']}")

    selected = select_scan_universe(universe, limit)
    if selected.empty:
        raise RuntimeError("The cached exchange universe is empty")

    downloaded = fetch_many(selected, workers=workers)
    market = fetch_market_context()
    news_bundle = fetch_market_news()

    results, histories = [], {}
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
    base["news_flags"] = pd.Series([[] for _ in range(len(base))], index=base.index, dtype="object")

    # Enrich only the leading 35 technical candidates. A small bounded pool
    # reduces wall-clock time without flooding public RSS endpoints.
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
        "news_count": news_bundle["total_items"],
        "news_sources_working": news_bundle["working_sources"],
        "news_sources_total": news_bundle["total_sources"],
        "news_source_status": news_bundle["source_status"],
        "global_news": news_bundle["global_news"][:6],
        "official_news": news_bundle["official_news"][:10],
        "benchmarks": market.get("benchmarks", {}),
        "nse_selected": int((selected["exchange"].astype(str).str.upper() == "NSE").sum()),
        "bse_selected": int((selected["exchange"].astype(str).str.upper() == "BSE").sum()),
    }
