# India Stock Radar — Free Data Edition

## Important cost clarification
Dhan's Trading API and Dhan's Data API are separate. Dhan's official support page says Trading API is free, while Data API (live market prices, historical intraday, daily data, market depth) costs ₹499 + applicable taxes/month. This free build does NOT call Dhan Data API. It uses Yahoo Finance through `yfinance` for daily OHLCV and public Google News RSS headlines. This source is unofficial, may be delayed/incomplete/rate-limited and is not suitable as a guaranteed real-time execution feed.

## Install (Windows)
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```
Add Telegram bot token and chat ID to `.env` only if you want alerts. No Dhan/Groww API key is required for free mode.

## Universe file
Upload a broad CSV with columns:
`symbol,company,exchange,sector,yahoo_symbol`
Examples: `RELIANCE.NS`, `TCS.NS`, `INFY.NS`. The included CSV has only five demo rows, not a full-market universe. Verify ticker mappings, delisted symbols and BSE suffixes.

## Current ranking
30% trend structure (EMA20/EMA50), 25% 5/20-day momentum, 20% relative volume, 10% RSI profile, 15% headline keyword sentiment. Missing relative volume is neutral. Headlines are simple keyword scoring and may be wrong; open the linked source and verify.

## Telegram
Create a bot using Telegram BotFather, send it a message, obtain chat ID, and store both values in `.env`. Never share bot tokens in chat.

## No automated trading
The application only produces a research shortlist and optional Telegram alerts. It does not place orders. Scores are not calibrated probabilities. Validate performance prospectively before risking money.


## Optional free broker account connections (read-only)
You may connect both Dhan and Groww using their free Trading/portfolio APIs for holdings, positions and available funds/margin information. This does NOT unlock live market data.
Add credentials to `.env`:
- `DHAN_ACCESS_TOKEN`: Dhan individual access token
- `GROWW_ACCESS_TOKEN`: Groww free-plan access token (Groww documents access-token expiry at 6:00 AM daily)
Then use **Fetch Dhan + Groww holdings, positions and available funds** in the dashboard.
The adapter calls only read-only endpoints:
- Dhan: `GET /v2/holdings`, `GET /v2/positions`, `GET /v2/fundlimit`
- Groww: `GET /v1/holdings/user`, `GET /v1/positions/user`, `GET /v1/margins/detail/user`
No order placement, modification or cancellation is implemented.

Pricing caveat: Dhan Trading APIs are free; Dhan Data APIs cost ₹499 + GST/month. Groww's ₹0 Free Trial excludes Live Data and Backtesting APIs, but includes other APIs such as portfolio and orders. This project does not call paid market-data endpoints from either broker.
