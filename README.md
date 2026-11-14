# India Stock Radar — Recommendation Model v2

## What changed
- EMA20/EMA50 trend structure and EMA20 slope.
- 5-, 20- and 60-session momentum, plus relative strength versus Nifty.
- Relative volume based on the median of the prior 20 sessions; the score impact is capped.
- RSI, ATR volatility, median traded value, gap size, Nifty regime and data age affect ranking and eligibility.
- Candidate lists reject stale data (over five calendar days), median traded value below ₹1 crore/day and extreme gap-plus-volume anomalies.
- ATR-based close-reference entry zone, stop and targets.
- News sentiment can change the score by at most four points in either direction.
- A local CSV ledger records picks and 5-/20-session forward close returns.

## Important limitations
This is a research shortlist, not a return guarantee, calibrated profit probability or order system. Market data comes from Yahoo Finance via yfinance, an unofficial source that can be delayed, incomplete, throttled or unavailable. The displayed prices and levels are based on the last daily close, not live quotes.

No official delivery-volume, FII/DII, audited fundamental, or corporate-announcement feed is integrated. Missing information is not silently treated as bullish. Review primary filings and news independently. The filters may return fewer than five names in a price band.

The forward ledger does not simulate intraday stop/target sequencing, brokerage, taxes, slippage, corporate actions or survivorship bias. It is a prospective monitoring aid, not proof of a profitable strategy. Validate out of sample before risking capital.

Dhan/Groww connections are optional read-only portfolio panels; they do not provide quote scanning and no orders are placed. Store tokens in a local .env file only. Never commit credentials.

## Install on Windows
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

Optional local environment variables: DHAN_ACCESS_TOKEN, GROWW_ACCESS_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

## Universe CSV
Required columns: symbol, company, exchange, sector, yahoo_symbol. Verify mappings, suspended/delisted names and BSE suffixes.

## Component weighting
Trend 22%, momentum 18%, Nifty-relative strength 15%, volume quality 10%, RSI 10%, traded-value liquidity 10%, ATR volatility 10%, Nifty regime 5%. If relative strength is unavailable, available weights are normalized. Headline overlay is separate and capped at +/-4 points.

## Security
The tracked .env file was removed from the recommendation-v2 branch. Deleting a file from the current tree does not erase credentials from Git history. Rotate any credential ever committed publicly and purge exposed secrets from the repository history.
