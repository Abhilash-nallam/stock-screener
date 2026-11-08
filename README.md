# NSE Stock Screener Automation

A Python-based NSE-focused research screener that collects stock data, calculates fundamental and technical indicators, ranks candidates, creates reports, and can send optional Telegram/email alerts.

> **Important:** This is a research tool, not investment advice or a guarantee of returns. Validate data and strategy performance before risking money.

## Features
- NSE top-gainer discovery with a fallback liquid-stock universe
- Yahoo Finance price history and available company fundamentals
- RSI, moving averages, volume spike and relative-strength indicators
- Fundamental, valuation, technical, momentum and risk scoring
- Top-five candidate report with illustrative entry/stop/target levels
- Optional Telegram and Gmail notifications
- Flask dashboard
- Historical backtesting and synthetic-data self-test

## Local setup

Use Python 3.10 or newer.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

python -m pip install -r requirements.txt
python main.py
```

Start the dashboard in another terminal:

```bash
python dashboard.py
```

Open http://localhost:5000.

## Backtesting

Run the no-network synthetic-data check:

```bash
python backtest.py --self-test
```

Run a historical test (requires internet and market-data availability):

```bash
python backtest.py --period 2y
```

The full-model historical score uses current fundamentals against past prices and therefore has look-ahead bias. Treat the technical-only results as the more meaningful test, and remember that even those results do not establish future profitability.

## Optional notifications

Set environment variables before running the screener:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SMTP_EMAIL`
- `SMTP_PASSWORD` (Gmail App Password)
- `ALERT_EMAIL_TO`

Never commit real credentials or a local `.env` file.

## Deployment note

The dashboard and daily screening job can be deployed as separate services. A file written by a scheduled job may not be visible to a separate web service on an ephemeral filesystem; use a shared persistent database/storage for a reliable hosted deployment.

## Data and limitations

- NSE scraping may fail or be rate-limited; a fallback stock universe is provided.
- Yahoo Finance data coverage and availability vary by symbol.
- Scoring weights are heuristic assumptions, not a validated predictive model.
- Entry, stop-loss and target levels are illustrative calculations, not guaranteed execution prices.
- Backtests should account for survivorship bias, slippage, brokerage, taxes and out-of-sample performance.
