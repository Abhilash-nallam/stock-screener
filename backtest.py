"""Historical backtesting utilities. Fundamental scores use current data and are biased."""
import argparse
import os
import numpy as np
import pandas as pd
import data_sources as ds
import technical_analysis as ta
import scoring

FORWARD_WINDOWS=[5,10,20]
MIN_LOOKBACK=200
SAMPLE_EVERY=5

def score_technical_only(tech,pct_today):
    t,_=scoring.score_technical(tech);m,_=scoring.score_momentum(tech,pct_today)
    return round((t+m)/40*100,1)

def run_backtest_for_symbol(symbol,df,nifty_df,fund):
    rows=[];n=len(df);max_fwd=max(FORWARD_WINDOWS)
    if n<MIN_LOOKBACK+max_fwd+1:return rows
    for i in range(MIN_LOOKBACK,n-max_fwd,SAMPLE_EVERY):
        hist=df.iloc[:i+1];nifty=nifty_df.iloc[:i+1] if nifty_df is not None else None
        tech=ta.analyze(hist,nifty)
        if tech is None:continue
        pct=(df["Close"].iloc[i]/df["Close"].iloc[i-1]-1)*100
        full=scoring.compute_score(symbol,fund,tech,pct)
        entry=df["Close"].iloc[i]
        row={"symbol":symbol,"date":df.index[i],"technical_score":score_technical_only(tech,pct),
             "full_model_score_biased":full["total_score"],"entry_price":round(entry,2)}
        for w in FORWARD_WINDOWS:
            row[f"fwd_return_{w}d"]=round((df["Close"].iloc[i+w]/entry-1)*100,2)
        rows.append(row)
    return rows

def run_backtest(symbols,period="2y"):
    print(f"Running backtest on {len(symbols)} symbols, {period} history...")
    nifty=ds.get_nifty_history(period);rows=[]
    for symbol in symbols:
        try:
            fund=ds.get_fundamentals(symbol);ds.throttle()
            hist=ds.get_price_history(symbol,period);ds.throttle()
            recs=run_backtest_for_symbol(symbol,hist,nifty,fund);rows.extend(recs)
            print(f"  {symbol}: {len(recs)} samples")
        except Exception as e:print(f"  [warn] skipped {symbol}: {e}")
    return pd.DataFrame(rows)

def bucket_label(score):
    if score>=80:return "80-100"
    if score>=70:return "70-79"
    if score>=55:return "55-69"
    if score>=40:return "40-54"
    return "0-39"

def analyze(df,score_col="technical_score"):
    if df.empty:return pd.DataFrame()
    work=df.copy();work["bucket"]=work[score_col].apply(bucket_label);rows=[]
    for bucket,group in work.groupby("bucket"):
        row={"bucket":bucket,"n_samples":len(group)}
        for w in FORWARD_WINDOWS:
            col=f"fwd_return_{w}d"
            row[f"avg_return_{w}d"]=round(group[col].mean(),2)
            row[f"win_rate_{w}d"]=round((group[col]>0).mean()*100,1)
        rows.append(row)
    order=["0-39","40-54","55-69","70-79","80-100"]
    out=pd.DataFrame(rows);out["bucket"]=pd.Categorical(out["bucket"],categories=order,ordered=True)
    return out.sort_values("bucket").reset_index(drop=True)

def correlation_check(df,score_col="technical_score"):
    if df.empty or len(df)<10:return None
    return round(df[score_col].corr(df["fwd_return_10d"]),3)

def build_report(df,tech_stats,full_stats,corr_tech,corr_full,period):
    lines=[f"# Backtest Report — {period} history, {len(df)} samples","",
    "> Fundamental/valuation scores use today's data on past prices (look-ahead bias). Technical-only results are more meaningful, but still do not predict future returns.","",
    "## Technical-only score vs forward returns",f"10-day correlation: **{corr_tech}**",""]
    if not tech_stats.empty:
        lines+=["| Score | Samples | Avg 5d | Win 5d | Avg 10d | Win 10d | Avg 20d | Win 20d |","|---|---:|---:|---:|---:|---:|---:|---:|"]
        for _,r in tech_stats.iterrows():
            lines.append(f"| {r['bucket']} | {r['n_samples']} | {r['avg_return_5d']}% | {r['win_rate_5d']}% | {r['avg_return_10d']}% | {r['win_rate_10d']}% | {r['avg_return_20d']}% | {r['win_rate_20d']}% |")
    lines+=["","## Full model (biased; comparison only)",f"10-day correlation: **{corr_full}**",""]
    if not full_stats.empty:
        lines+=["| Score | Samples | Avg 5d | Win 5d | Avg 10d | Win 10d |","|---|---:|---:|---:|---:|---:|"]
        for _,r in full_stats.iterrows():
            lines.append(f"| {r['bucket']} | {r['n_samples']} | {r['avg_return_5d']}% | {r['win_rate_5d']}% | {r['avg_return_10d']}% | {r['win_rate_10d']}% |")
    lines+=["","Small samples are unreliable. Include costs, slippage and out-of-sample tests before evaluating a strategy."]
    return "\n".join(lines)

def plot_buckets(stats,path="reports/backtest_chart.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if stats.empty:return None
    os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
    fig,ax=plt.subplots(figsize=(7,4));ax.bar(stats["bucket"].astype(str),stats["avg_return_10d"])
    ax.set_xlabel("Technical score bucket");ax.set_ylabel("Average 10-day forward return (%)")
    ax.set_title("Score bucket vs forward return");ax.axhline(0,linewidth=.8);fig.tight_layout()
    fig.savefig(path,dpi=120);plt.close(fig);return path

def synthetic_data(n=600,seed=42,trend=.0005):
    rng=np.random.default_rng(seed);ret=rng.normal(trend,.015,n);close=100*np.cumprod(1+ret)
    dates=pd.bdate_range(end=pd.Timestamp.today(),periods=n)
    return pd.DataFrame({"Close":close,"Open":close*(1+rng.normal(0,.002,n)),
      "High":close*(1+abs(rng.normal(0,.006,n))),"Low":close*(1-abs(rng.normal(0,.006,n))),
      "Volume":rng.integers(100000,2000000,n)},index=dates)

def self_test():
    df=synthetic_data();nifty=synthetic_data(seed=1,trend=.0002)
    fund={"roe":.15,"debt_to_equity":40,"pe_ratio":18,"market_cap":50_000_000_000,"revenue_growth":.1}
    results=pd.DataFrame(run_backtest_for_symbol("SYNTHETIC",df,nifty,fund))
    a=analyze(results,"technical_score");b=analyze(results,"full_model_score_biased")
    report=build_report(results,a,b,correlation_check(results),correlation_check(results,"full_model_score_biased"),"synthetic")
    os.makedirs("reports",exist_ok=True)
    with open("reports/backtest_selftest.md","w") as f:f.write(report)
    plot_buckets(a,"reports/backtest_selftest_chart.png")
    print(report);print("Self-test complete.")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--period",default="2y")
    parser.add_argument("--symbols",nargs="*",default=None)
    args=parser.parse_args()
    if args.self_test:self_test()
    else:
        symbols=args.symbols or ds.get_universe_symbols()
        results=run_backtest(symbols,args.period)
        if results.empty:print("No results collected — check network and symbols.")
        else:
            os.makedirs("reports",exist_ok=True);results.to_csv("reports/backtest_raw.csv",index=False)
            a=analyze(results);b=analyze(results,"full_model_score_biased")
            report=build_report(results,a,b,correlation_check(results),correlation_check(results,"full_model_score_biased"),args.period)
            with open("reports/backtest_report.md","w") as f:f.write(report)
            plot_buckets(a);print(report)
