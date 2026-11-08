"""Historical backtesting utilities with safe sampling and progress checkpoints.

IMPORTANT: yfinance fundamentals are current values, not point-in-time history.
The technical-only score avoids this look-ahead bias. The full-model score is
included only as a clearly labelled, biased comparison.
"""
import argparse
import os
import random

import numpy as np
import pandas as pd

import data_sources as ds
import technical_analysis as ta
import scoring

FORWARD_WINDOWS = [5, 10, 20]
MIN_LOOKBACK = 200
SAMPLE_EVERY = 5
DEFAULT_MAX_SYMBOLS = 150
CHECKPOINT_EVERY = 20
CHECKPOINT_PATH = "reports/backtest_raw.csv"


def score_technical_only(tech, pct_today):
    """Score using only historical technical and momentum data."""
    technical_points, _ = scoring.score_technical(tech)
    momentum_points, _ = scoring.score_momentum(tech, pct_today)
    return round(((technical_points + momentum_points) / 40) * 100, 1)


def run_backtest_for_symbol(symbol, df, nifty_df, fund):
    """Score historical dates using only data available on each date."""
    records = []
    if df is None or df.empty or len(df) < MIN_LOOKBACK + max(FORWARD_WINDOWS) + 1:
        return records

    for i in range(MIN_LOOKBACK, len(df) - max(FORWARD_WINDOWS), SAMPLE_EVERY):
        history_slice = df.iloc[: i + 1]
        nifty_slice = nifty_df.iloc[: i + 1] if nifty_df is not None and not nifty_df.empty else None
        tech = ta.analyze(history_slice, nifty_slice)
        if tech is None:
            continue

        pct_today = (df["Close"].iloc[i] / df["Close"].iloc[i - 1] - 1) * 100
        full_score = scoring.compute_score(symbol, fund, tech, pct_today)
        entry_price = df["Close"].iloc[i]

        row = {
            "symbol": symbol,
            "date": df.index[i],
            "technical_score": score_technical_only(tech, pct_today),
            "full_model_score_biased": full_score["total_score"],
            "entry_price": round(entry_price, 2),
        }
        for window in FORWARD_WINDOWS:
            future_price = df["Close"].iloc[i + window]
            row[f"fwd_return_{window}d"] = round((future_price / entry_price - 1) * 100, 2)
        records.append(row)

    return records


def save_checkpoint(records, path=CHECKPOINT_PATH):
    """Persist collected rows so interrupted runs retain their progress."""
    if not records:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pd.DataFrame(records).to_csv(path, index=False, encoding="utf-8")
    print(f"  [checkpoint] saved {len(records)} samples to {path}")


def run_backtest(symbols, period="2y", checkpoint_every=CHECKPOINT_EVERY,
                 checkpoint_path=CHECKPOINT_PATH, stop_after_failures=10):
    print(f"Running backtest on {len(symbols)} symbols, {period} history...")
    nifty_df = ds.get_nifty_history(period=period)
    all_records = []
    consecutive_failures = 0

    try:
        for index, symbol in enumerate(symbols):
            try:
                fundamentals = ds.get_fundamentals(symbol)
                ds.throttle()
                history = ds.get_price_history(symbol, period=period)
                ds.throttle()

                rows = run_backtest_for_symbol(symbol, history, nifty_df, fundamentals)
                all_records.extend(rows)
                print(f"  [{index + 1}/{len(symbols)}] {symbol}: {len(rows)} samples")
                consecutive_failures = 0

            except KeyboardInterrupt:
                print("\n[info] Interrupted by user. Saving collected progress...")
                break
            except Exception as exc:
                consecutive_failures += 1
                print(f"  [{index + 1}/{len(symbols)}] [warn] {symbol} failed: {exc}")
                if consecutive_failures >= stop_after_failures:
                    print(f"[warn] {stop_after_failures} consecutive failures; stopping early.")
                    break

            if (index + 1) % checkpoint_every == 0:
                save_checkpoint(all_records, checkpoint_path)

    except KeyboardInterrupt:
        print("\n[info] Interrupted by user. Saving collected progress...")
    finally:
        save_checkpoint(all_records, checkpoint_path)

    return pd.DataFrame(all_records)


def bucket_label(score):
    if score >= 80:
        return "80-100"
    if score >= 70:
        return "70-79"
    if score >= 55:
        return "55-69"
    if score >= 40:
        return "40-54"
    return "0-39"


def analyze(results_df, score_col="technical_score"):
    if results_df.empty:
        return pd.DataFrame()

    work = results_df.copy()
    work["bucket"] = work[score_col].apply(bucket_label)
    rows = []
    for bucket, group in work.groupby("bucket", observed=False):
        row = {"bucket": bucket, "n_samples": len(group)}
        for window in FORWARD_WINDOWS:
            column = f"fwd_return_{window}d"
            row[f"avg_return_{window}d"] = round(group[column].mean(), 2)
            row[f"win_rate_{window}d"] = round((group[column] > 0).mean() * 100, 1)
        rows.append(row)

    order = ["0-39", "40-54", "55-69", "70-79", "80-100"]
    output = pd.DataFrame(rows)
    output["bucket"] = pd.Categorical(output["bucket"], categories=order, ordered=True)
    return output.sort_values("bucket").reset_index(drop=True)


def correlation_check(results_df, score_col="technical_score"):
    if results_df.empty or len(results_df) < 10:
        return None
    return round(results_df[score_col].corr(results_df["fwd_return_10d"]), 3)


def build_report(results_df, stats_technical, stats_full, corr_technical, corr_full, period):
    lines = [
        f"# Backtest Report — {period} history, {len(results_df)} total samples",
        "",
        "> Current fundamentals applied to historical prices create look-ahead bias. "
        "Only technical-score results avoid that specific bias; neither result guarantees future returns.",
        "",
        "## Technical-only score vs forward returns (primary result)",
        f"10-day correlation: **{corr_technical}**",
        "",
    ]

    if not stats_technical.empty:
        lines += [
            "| Score bucket | Samples | Avg 5d | Win 5d | Avg 10d | Win 10d | Avg 20d | Win 20d |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for _, row in stats_technical.iterrows():
            lines.append(
                f"| {row['bucket']} | {row['n_samples']} | {row['avg_return_5d']}% | "
                f"{row['win_rate_5d']}% | {row['avg_return_10d']}% | "
                f"{row['win_rate_10d']}% | {row['avg_return_20d']}% | {row['win_rate_20d']}% |"
            )
    else:
        lines.append("Not enough data collected to calculate score buckets.")

    lines += [
        "",
        "## Full model (biased: today's fundamentals applied to past dates)",
        f"10-day correlation: **{corr_full}**",
        "",
    ]
    if not stats_full.empty:
        lines += [
            "| Score bucket | Samples | Avg 5d | Win 5d | Avg 10d | Win 10d |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for _, row in stats_full.iterrows():
            lines.append(
                f"| {row['bucket']} | {row['n_samples']} | {row['avg_return_5d']}% | "
                f"{row['win_rate_5d']}% | {row['avg_return_10d']}% | {row['win_rate_10d']}% |"
            )

    lines += [
        "",
        "## Interpretation cautions",
        "- Compare high-score buckets with low-score buckets; a high correlation alone is not proof of a tradable edge.",
        "- Samples overlap in time and across stocks, so they are not independent observations.",
        "- This test does not include brokerage, taxes, slippage, survivorship bias, or out-of-sample validation.",
        "- Small bucket counts make averages and win rates unstable.",
    ]
    return "\n".join(lines)


def plot_buckets(stats_df, path="reports/backtest_chart.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if stats_df.empty:
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fig, axis = plt.subplots(figsize=(7, 4))
    axis.bar(stats_df["bucket"].astype(str), stats_df["avg_return_10d"])
    axis.set_xlabel("Technical score bucket")
    axis.set_ylabel("Average 10-day forward return (%)")
    axis.set_title("Score bucket vs forward return")
    axis.axhline(0, linewidth=0.8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def synthetic_data(n=600, seed=42, trend=0.0005):
    rng = np.random.default_rng(seed)
    returns = rng.normal(trend, 0.015, n)
    close = 100 * np.cumprod(1 + returns)
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    return pd.DataFrame(
        {
            "Close": close,
            "Open": close * (1 + rng.normal(0, 0.002, n)),
            "High": close * (1 + abs(rng.normal(0, 0.006, n))),
            "Low": close * (1 - abs(rng.normal(0, 0.006, n))),
            "Volume": rng.integers(100_000, 2_000_000, n),
        },
        index=dates,
    )


def self_test():
    print("Running self-test on synthetic data (no network calls)...")
    history = synthetic_data()
    nifty = synthetic_data(seed=1, trend=0.0002)
    fundamentals = {
        "roe": 0.15,
        "debt_to_equity": 40,
        "pe_ratio": 18,
        "market_cap": 50_000_000_000,
        "revenue_growth": 0.1,
    }
    results = pd.DataFrame(
        run_backtest_for_symbol("SYNTHETIC", history, nifty, fundamentals)
    )
    stats_technical = analyze(results, "technical_score")
    stats_full = analyze(results, "full_model_score_biased")
    report = build_report(
        results,
        stats_technical,
        stats_full,
        correlation_check(results, "technical_score"),
        correlation_check(results, "full_model_score_biased"),
        "synthetic",
    )
    os.makedirs("reports", exist_ok=True)
    with open("reports/backtest_selftest.md", "w", encoding="utf-8") as output:
        output.write(report)
    plot_buckets(stats_technical, "reports/backtest_selftest_chart.png")
    print(report)
    print("Self-test complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true",
                        help="Run on synthetic data without network calls")
    parser.add_argument("--period", default="2y", help="History period, e.g. 1y or 2y")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="Optional explicit list of symbols to test")
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS,
                        help="Maximum random universe sample; use 0 to disable the cap")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed so the same sample can be reproduced")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        symbols = args.symbols or ds.get_universe_symbols()
        if args.max_symbols > 0 and len(symbols) > args.max_symbols:
            random.seed(args.seed)
            print(
                f"[info] universe has {len(symbols)} symbols; randomly sampling "
                f"{args.max_symbols} (seed={args.seed})"
            )
            symbols = random.sample(symbols, args.max_symbols)

        results_df = run_backtest(symbols, period=args.period)
        if results_df.empty:
            print("No results collected. Check connectivity, symbols, and Yahoo Finance availability.")
        else:
            os.makedirs("reports", exist_ok=True)
            results_df.to_csv(CHECKPOINT_PATH, index=False, encoding="utf-8")
            stats_technical = analyze(results_df, "technical_score")
            stats_full = analyze(results_df, "full_model_score_biased")
            corr_technical = correlation_check(results_df, "technical_score")
            corr_full = correlation_check(results_df, "full_model_score_biased")
            report = build_report(
                results_df, stats_technical, stats_full,
                corr_technical, corr_full, args.period
            )
            with open("reports/backtest_report.md", "w", encoding="utf-8") as output:
                output.write(report)
            plot_buckets(stats_technical)
            print(report)
            print("\nSaved: reports/backtest_raw.csv, reports/backtest_report.md, reports/backtest_chart.png")
