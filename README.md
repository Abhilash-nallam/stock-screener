# India Stock Radar

A Streamlit dashboard plus a separate long-polling Telegram command worker.

## Main capabilities
- Combined NSE + BSE listed-equity universe with separate refreshes and cached source files.
- Telegram commands and inline buttons for 250-stock or 500-stock scans.
- Telegram commands to refresh NSE, BSE, or both universes and to inspect cache counts.
- Detailed stock cards with price, score, 1D/5D/20D performance, entry reference, stop, targets, risk, RSI, relative volume and data date.
- Positive/negative moves use green/red emoji indicators. Telegram does not support arbitrary text colours.
- Streamlit dashboard with exchange refresh controls, scan selector, stock tables, planning levels and forward-test ledger.
- Optional Dhan/Groww read-only portfolio panels.

## Important market-data limitations
Daily OHLCV uses Yahoo Finance via yfinance, an unofficial source that can be delayed, incomplete, rate-limited or unavailable. It is not a live execution feed. NSE security list uses the public NSE equity CSV. BSE list uses BSE's public active-equity scrip endpoint and maps scrip codes to Yahoo `.BO` tickers; public endpoints may change or throttle. Confirm ticker mapping and source data before using a name.
The model is a research ranking heuristic, not a calibrated probability or a promise of returns. It does not include complete official delivery statistics, FII/DII series, audited fundamentals or an exchange filing classifier.

## Run locally (Windows)
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

## Telegram bot — separate always-on worker
The Streamlit UI does not keep a Telegram listener alive. For Telegram commands at any time, run a separate worker:
```bat
python telegram_bot.py
```
The bot and dashboard can use the same `.env` locally. Add these environment variables to the worker:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` (the private chat that is authorised to control the scanner)
- Optional `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated extra authorised chat IDs)

Open Telegram and use `/start`. It displays buttons:
- Scan 250 stocks
- Scan 500 stocks
- Refresh NSE
- Refresh BSE
- Refresh NSE + BSE
- Universe status

Commands also work: `/scan 250`, `/scan 500`, `/refresh_nse`, `/refresh_bse`, `/refresh_all`, `/status`, `/help`.
Only the configured chat ID and optional allow-list can control the scanner. Do not publish bot tokens or make the bot a public command endpoint.

## Streamlit Community Cloud
Deploy the repository branch `new`, main file `app.py`. Add root-level Secrets:
```toml
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_private_chat_id"
```
The dashboard test and shortlist buttons use these secrets. The bot worker requires its own environment variables; Streamlit Secrets are not automatically shared with another hosting service.

## Deploy Telegram worker on Render
Use the included `render.yaml` Blueprint to create a Background Worker. Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the Render environment. Render background workers require a paid instance; the free web service type is not a reliable always-on bot worker. For a no-hosting-cost test, run `python telegram_bot.py` on your own PC while it is powered on and connected.
Use only one polling worker per bot token. Telegram long polling conflicts with a webhook or a second concurrent polling worker.

## Telegram report format
Each scan sends:
1. Market/date and scan coverage summary.
2. Top candidates priced up to ₹1,000.
3. Top candidates priced above ₹1,000.
4. Green/red icons for positive/negative returns, yellow/green/red risk flags, and individual entries/stops/targets.

## Forward-test ledger
The dashboard and worker write to a local CSV under `data/recommendation_ledger.csv`. Separate hosting services do not share their local filesystems, and local disks may be reset during redeploys. Use a shared persistent database for a durable cross-service ledger if required.

## Security
Never commit `.env` or credentials to Git. Rotate any token that has ever been committed to a public repository. Telegram bot commands are restricted to configured chat IDs.
