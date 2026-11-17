# India Stock Radar

A private-command Telegram scanner with an optional Streamlit dashboard.

## Hosting architecture — free tiers
- **Streamlit Community Cloud:** optional visual dashboard. Public viewers cannot trigger scans unless the owner configures and enters a private dashboard password.
- **Cloudflare Workers Free:** receives Telegram webhook commands (100,000 requests/day plan allowance).
- **GitHub Actions:** runs the Python scanner only when requested. Standard GitHub-hosted runners are free for public repositories.
- No always-on Python worker, Render Background Worker, VPS or home PC is needed.

The GitHub repository must remain public to use the unlimited standard hosted-runner allowance described by GitHub. Cloudflare Workers Free has service limits; this is not an unlimited compute plan.

## Telegram features
- `/start` or `/menu`: show the inline action menu. `/help` and the Help button direct users to the dedicated support bot [@DigitalSupportDesk_Bot](https://t.me/DigitalSupportDesk_Bot).
- `/fetch 250` or `/fetch 500`: run the scan and send both daily delivery/swing watchlists and intraday-confirmed watchlists. Outside market hours, the command still runs completed-daily-candle research and reports delivery candidates; intraday confirmation is only attempted during the open session.
- `/refresh_nse`, `/refresh_bse`, `/refresh_all`: refresh exchange universes.
- `/status`: report cached NSE/BSE universe counts.
- Inline buttons provide the same actions.
- Reports contain market regime, coverage, top daily delivery/swing candidates and separate intraday-confirmed candidates in each price band, company/exchange, latest completed 5-minute candle close, daily model score, intraday score, 1D/5D/20D changes, VWAP, entry/stop/target references, risk, RSI and volume evidence.
- Positive/negative moves use green/red icons. Telegram does not support arbitrary HTML text colours.

## Market-data limitations
Daily OHLCV comes from Yahoo Finance via yfinance, an unofficial source that may be delayed, incomplete or throttled. It is not a live execution feed.
The NSE list is downloaded from the public NSE equity CSV. The BSE list is sourced from a public BSE active-scrip endpoint; that endpoint may change or rate-limit. The scanner combines the two lists and uses ISIN de-duplication where matching ISINs exist.
Model scores are heuristic rankings, not calibrated profit probabilities or guarantees. Full official delivery-volume, FII/DII, audited fundamentals and a corporate-filings classifier are not currently integrated.
Daily technical scores use completed daily candles. Intraday levels use the latest completed 5-minute candle close and ATR references; neither is an exchange-certified real-time quote or an order instruction.

## Deploy the dashboard
Deploy on Streamlit Community Cloud:
- Repository: `Abhilash-nallam/stock-screener`
- Branch: `new`
- Main file: `app.py`

For a public Streamlit deployment, do not add Telegram bot tokens, GitHub PATs, broker access tokens or broker credentials to Streamlit Secrets. Manual dashboard scans are disabled by default. To enable them, add one private password:
```toml
RADAR_DASHBOARD_PASSWORD = "use-a-long-random-password"
```
Only the owner should enter this password. Telegram scans continue to run through the separate private Telegram → Cloudflare → GitHub Actions route.

## Configure GitHub Actions secrets
In GitHub repository **Settings → Secrets and variables → Actions → New repository secret**, create:
- `TELEGRAM_BOT_TOKEN`: the BotFather token.
- `TELEGRAM_CHAT_ID`: your authorised personal chat ID.

The repository is public, but Actions secrets are not exposed in repository source. Never put tokens in code, issues, logs or commits. The scanner workflow receives only the Telegram bot token and your private chat ID; no Groww or Dhan market-data credentials are required.

## Deploy the Cloudflare Telegram webhook
1. Sign in to Cloudflare and open **Workers & Pages**.
2. Create a Worker named e.g. `india-stock-radar-bot`.
3. Open **Edit code** and paste the complete contents of `cloudflare/telegram-worker.js`.
4. Under **Settings → Variables and Secrets**, add these as secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `TELEGRAM_WEBHOOK_SECRET` (random 32+ character string using letters, digits, underscore or hyphen)
   - `GITHUB_ACTIONS_TOKEN` (fine-grained GitHub PAT)
   - `SETUP_KEY` (another long random secret used only for webhook registration)
5. Deploy the Worker. Its public URL will look like `https://india-stock-radar-bot.<account>.workers.dev`.

### Create the GitHub token for the webhook
Create a fine-grained personal access token in GitHub:
- Resource owner: your account.
- Repository access: only `stock-screener`.
- Repository permissions: **Actions — Read and write**.
- Metadata read is automatically included.
Store this value only as Cloudflare Worker secret `GITHUB_ACTIONS_TOKEN`. Do not add it to repository source.

### Register the Telegram webhook once
On Windows PowerShell, replace the two placeholders and run:
```powershell
$worker = "https://YOUR-WORKER.YOUR-ACCOUNT.workers.dev"
$setupKey = "YOUR_SETUP_KEY"
$body = @{ webhook_url = "$worker/telegram/webhook" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$worker/admin/register" -Headers @{ "X-Setup-Key" = $setupKey } -ContentType "application/json" -Body $body
```
A successful response shows `webhook_registered: true`. The Worker sets the Telegram webhook and bot command menu. Once webhook mode is enabled, Telegram `getUpdates` polling is not used.

Test the Worker health URL: `https://YOUR-WORKER.YOUR-ACCOUNT.workers.dev/health`.

## How a Telegram scan runs
1. Telegram posts an update to Cloudflare Worker.
2. Cloudflare validates the Telegram webhook secret, private-chat type, sender ID and authorised chat ID. It also rejects oversized payloads, throttles rapid commands and requires a long setup key for webhook registration.
3. Cloudflare calls GitHub's workflow-dispatch API.
4. GitHub Actions installs the lightweight scanner dependencies, restores the exchange-list cache, and runs `telegram_action.py`.
5. The Python job posts the formatted scan or refresh report to Telegram.
6. The exchange cache is saved for a future run.

The GitHub runner is temporary; there is no process to keep alive. The Actions cache is temporary and subject to GitHub's cache retention/eviction policy.

## Run locally (optional)
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

For local Telegram long polling only, `python telegram_bot.py` remains available. Do not run polling and webhook mode at the same time with the same Telegram bot token.

## Forward-test ledger
The dashboard uses a local CSV ledger under `data/recommendation_ledger.csv`. GitHub Actions also stores a temporary CSV forward-test ledger in the `data/` cache; cache retention and eviction are controlled by GitHub, so it is not a permanent database. New intraday picks use the recorded latest completed 5-minute candle close as the forward-test entry basis; older ledger rows without a live entry retain their daily-close basis. Do not compare the two groups without accounting for this basis difference.

## Security
- Never commit `.env`, Telegram tokens, Cloudflare secrets, broker tokens or GitHub PATs.
- Rotate any token ever committed publicly.
- Restrict the Telegram webhook to your private chat and sender ID.
- Use a fine-grained GitHub token scoped only to this repository with Actions read/write permission.
- The public Streamlit dashboard does not expose broker holdings or Telegram send buttons. Manual scans require `RADAR_DASHBOARD_PASSWORD`; leave it unset if the dashboard is only for viewing.
- GitHub Actions use immutable action commit SHAs, full-project Python compilation, unit tests, JavaScript syntax checks and a Python dependency vulnerability audit.
- The Worker source in this repository is not auto-deployed by GitHub. After changing `cloudflare/telegram-worker.js`, paste the updated file into Cloudflare Workers and deploy it.


## Model v2 data coverage (latest upgrade)

### Market data and indicators
- One-year adjusted daily OHLCV via Yahoo Finance/yfinance where available (unofficial, potentially delayed/incomplete; not a live quote feed).
- India benchmarks: Nifty 50, Sensex and India VIX. Global benchmarks: S&P 500, Nasdaq, Dow, FTSE, Nikkei and Hang Seng. Macro proxies: USD/INR, Brent and gold.
- Technical factors: EMA20/50/200 when enough bars exist, Wilder-style RSI/ATR, MACD histogram, ADX, 5/20/60/120-session momentum, multi-horizon relative strength versus Nifty, 55-session-high proximity, volume, traded-value liquidity and market regime.

### News and official sources attempted on each scan
- NSE RSS: announcements, daily buyback, shareholding-pattern, BRSR filings and circulars.
- BSE corporate announcements RSS.
- SEBI RSS, RBI press-release/notification RSS and PIB government-release RSS.
- GDELT DOC multilingual global news query for India/global markets, central banks, geopolitics, tariffs, crude, semiconductors and related macro topics.
- Global RSS headlines: BBC World/Business/Asia, CNBC World/Asia/Economy and The Guardian Business.
- Google News RSS company-specific query for the leading 35 preliminary technical candidates.
- Stories carry source, timestamp and URL; duplicates and items older than five days are filtered when timestamps exist. The source-health summary shows which feeds responded during each scan. Company-news queries run in a bounded concurrent pool.

### Coverage limits — read before relying on a report
This is a curated feed-and-query system, not a crawl of every Indian or global website. It cannot guarantee finding every article, filing, social post, interview or analyst view. Company-specific searches are performed only for the leading 35 preliminary candidates; the global and official feeds are ingested more broadly. Headline sentiment is keyword-based, not full-article interpretation, and can misread context, negation or entity names. GDELT and public RSS providers may rate-limit or be unavailable.

The NSE list is fetched from its public EQ CSV. BSE refresh first tries the public BSE listing JSON endpoint with a session and modern browser headers, then falls back to the official SCRIP.ZIP scrip-master download. BSE can still block automated requests or change its file format; if both sources fail, the bot reports the exact error and preserves the prior cache. A BSE announcements feed is separate from the BSE scrip-master endpoint. Do not assume complete BSE universe coverage until refresh succeeds.

### Rotating universe
A 250-stock request selects up to 200 NSE plus 50 BSE-exclusive names; a 500-stock request selects up to 400 plus 100. The start point rotates by India calendar date, avoiding the prior alphabetical-first-symbol bias. A scan is a sample per request, not a simultaneous scan of all listed companies; price-fetch failures reduce coverage and are reported.

### Interpretation
The score is a transparent heuristic ranking, not a calibrated probability of profit or guaranteed prediction. The model still lacks a complete audited-fundamentals feed, official delivery-volume history, complete FII/DII flows, institutional order-book data and a full exchange-filings document parser. Entry, stop and target levels use the last available adjusted daily close and ATR; they are not live quotes or trade orders.

## Hosting clarification
Streamlit is optional and only hosts the visual dashboard. The Telegram workflow does not pass through Streamlit: Telegram -> Cloudflare Worker -> GitHub Actions -> Python scanner -> Telegram. GitHub Actions runs a temporary cloud runner only when a Telegram command dispatches a job.


## Pre-market preparation and opening-gap process

- Running `/fetch 250` or `/fetch 500` before 09:15 IST produces a dedicated pre-market preparation report using the previous completed daily session only. During the 09:00–09:15 pre-open phase it still does not treat indicative prices as confirmed trades.
- The report shows previous close, previous-session high/low, 20-session support/resistance references, prior-session volume versus its prior-20-session median, daily momentum/trend, company headline context, and timestamped global/official headlines published within the last 24 hours.
- Pre-market candidates are research watchlists, not buy signals. This feed does not currently ingest the exchange/broker pre-open indicative equilibrium price and quantity. Therefore it cannot truthfully label a stock as an actual gap-up or gap-down before an opening price is available.
- Once the market opens and the scanner has valid intraday data, the report separately classifies observed opening gaps: at least +0.50% as gap-up and at most -0.50% as gap-down, measured from the session open against the previous completed daily close. The gap list is a researched shortlist, not the entire exchange.
- The intraday confirmation layer still requires six consecutive completed 5-minute candles, expanding volume, a fresh provider timestamp, price above VWAP, positive momentum, and Nifty time alignment. On a normal session, this is usually no earlier than about 09:45 IST.
- **The 09:45 handoff is not currently scheduled automatically.** Send `/fetch 250` or `/fetch 500` again around 09:45 IST to run intraday confirmation. The current GitHub workflow is manual-dispatch only; no automatic recurring scan has been enabled.

## Zero-cost market-open intraday mode (no Groww subscription required)

The default Telegram scan uses Yahoo Finance's public 5-minute chart data for NSE `.NS` and BSE `.BO` tickers. It does not call Groww live-data endpoints, broker order APIs, or any paid market-data API. The Groww API key/secret entries in GitHub Actions are not used by this zero-cost scanner and may be removed from repository secrets. Do not share them.

Important limitation: Yahoo Finance is an unofficial public data route. Its 5-minute candles may be delayed, stale, missing for some symbols, or temporarily unavailable. The displayed intraday price is the latest completed 5-minute candle close, not an exchange-certified real-time last-traded price. The scanner blocks candles older than 10 minutes, excludes the currently forming 5-minute candle, requires the first bar of the exchange session and checks the continuity of the six latest completed bars. It returns no candidate when intraday data is unavailable. Never rely on this feed alone for order execution; check the live quote and bid/ask in your broker app immediately before deciding.

The first confirmation requires the first session candle plus at least six consecutive completed 5-minute candles, an expanding-volume comparison, and a Nifty candle close within 10 minutes of the candidate's candle close. On a normal session, the earliest possible confirmation is around 09:45 IST or later. The latest candle must be no older than 10 minutes. High daily-risk candidates are excluded. Both NSE and BSE are attempted via `.NS` / `.BO` tickers, but Yahoo coverage differs by symbol and an unavailable BSE candle is skipped rather than treated as a negative signal.

Groww's Free Trial/API key is not the same as free live market data. Groww currently advertises free-trial access to Cloud and APIs other than Live Data and Backtesting; live quotes (LTP/OHLC) and historical candle access are included in its paid API subscription at ₹499/month plus taxes. The free API key can still be useful for other Groww APIs, but this stock scanner does not need it. See [Groww pricing](https://groww.in/trade-api), [free trial explanation](https://groww.in/blog/api-trading-on-groww), and [Live Data docs](https://groww.in/trade-api/docs/curl/live-data).

Groww's static-IP notice is relevant to API order placement. This repository's scanner does not send orders, so no static IP is needed. The old paid Groww live-market adapter has been removed; no paid broker market-data API is used by this free scanner.
### NSE/BSE universe cache behavior

Before scanning, the worker checks the NSE and BSE caches separately. If NSE exists but BSE is missing, it now attempts the BSE refresh independently instead of silently reporting a 0-BSE scan. If the BSE public endpoint fails, the report shows the reason and `/refresh_bse` can be used to retry. The 250/500 mixed universe uses a rotating sample (normally up to 80% NSE and 20% BSE-exclusive instruments); companies listed on both exchanges are deduplicated by ISIN, preferring NSE.

After refresh, Yahoo intraday coverage is still per-symbol and may be incomplete. A BSE scrip with no `.BO` 5-minute history is skipped; it is not counted as an actionable live quote.