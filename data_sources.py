"""Free NSE/Yahoo Finance data sources."""
import time
import pandas as pd
import yfinance as yf
try:
    from nsepython import nse_eq_symbols,nse_get_top_gainers
    NSEPYTHON_AVAILABLE=True
except Exception:
    NSEPYTHON_AVAILABLE=False
FALLBACK_UNIVERSE=["RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN","BHARTIARTL","KOTAKBANK","LT","AXISBANK","BAJFINANCE","MARUTI","ASIANPAINT","SUNPHARMA","TITAN","WIPRO","ULTRACEMCO","NESTLEIND","ADANIENT","TATAMOTORS","TATASTEEL","POWERGRID","NTPC"]
def get_top_gainers(limit=50):
    if NSEPYTHON_AVAILABLE:
        try:return pd.DataFrame(nse_get_top_gainers()).head(limit)
        except Exception as e:print(f"[warn] NSE top gainers failed: {e}")
    return pd.DataFrame()
def get_universe_symbols():
    if NSEPYTHON_AVAILABLE:
        try:
            symbols=nse_eq_symbols()
            if symbols:return symbols
        except Exception as e:print(f"[warn] NSE symbol fetch failed: {e}")
    print("[info] using fallback universe")
    return FALLBACK_UNIVERSE
def get_price_history(symbol,period="1y"):return yf.Ticker(f"{symbol}.NS").history(period=period)
def get_fundamentals(symbol):
    ticker=yf.Ticker(f"{symbol}.NS")
    try:info=ticker.info
    except Exception:info={}
    return {"roe":info.get("returnOnEquity"),"debt_to_equity":info.get("debtToEquity"),"pe_ratio":info.get("trailingPE"),"market_cap":info.get("marketCap"),"profit_margin":info.get("profitMargins"),"revenue_growth":info.get("revenueGrowth"),"sector":info.get("sector")}
def get_nifty_history(period="1y"):return yf.Ticker("^NSEI").history(period=period)
def throttle():time.sleep(0.6)
