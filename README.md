# India Stock Radar

A Streamlit dashboard and a serverless Telegram-controlled stock scanner.

## Hosting architecture — free tiers
- **Streamlit Community Cloud:** hosts the dashboard.
- **Cloudflare Workers Free:** receives Telegram webhook commands (100,000 requests/day plan allowance).
- **GitHub Actions:** runs the Python scanner only when requested. Standard GitHub-hosted runners are free for public repositories.
- No always-on Python worker, Render Background Worker, VPS or home PC is needed.

The GitHub repository must remain public to use the unlimited standard hosted-runner allowance described by GitHub. Cloudflare Workers Free has service limits; this is not an unlimited compute plan.

## Telegram features
- `/start` or `/help`: show the inline action menu.
- `/fetch 250` or `/fetch 500`: run the scan and send the report back in Telegram.
- `/refresh_nse`, `/refresh_bse`, `/refresh_all`: refresh exchange universes.
- `/status`: report cached NSE/BSE universe counts.
- Inline buttons provide the same actions.
- Reports contain market regime, scan coverage, top-five candidates in each price band, company/exchange, last close, score, 1D/5D/20D changes, entry reference, stop, two targets, risk, RSI and relative volume.
- Positive/negative moves use green/red icons. Telegram does not support arbitrary HTML text colours.

## Market-data limitations
Daily OHLCV comes from Yahoo Finance via yfinance, an unofficial source that may be delayed, incomplete or throttled. It is not a live execution feed.
The NSE list is downloaded from the public NSE equity CSV. The BSE list is sourced from a public BSE active-scrip endpoint; that endpoint may change or rate-limit. The scanner combines the two lists and uses ISIN de-duplication where matching ISINs exist.
Model scores are heuristic rankings, not calibrated profit probabilities or guarantees. Full official delivery-volume, FII/DII, audited fundamentals and a corporate-filings classifier are not currently integrated.
Displayed prices/entry/stop/targets are based on daily closes and are not live order instructions.

## Deploy the dashboard
Deploy on Streamlit Community Cloud:
- Repository: `Abhilash-nallam/stock-screener`
- Branch: `new`
- Main file: `app.py`

Add root-level Streamlit Secrets for its manual Telegram test/summary buttons:
```toml
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_private_chat_id"
```

## Configure GitHub Actions secrets
In GitHub repository **Settings → Secrets and variables → Actions → New repository secret**, create:
- `TELEGRAM_BOT_TOKEN`: the BotFather token.
- `TELEGRAM_CHAT_ID`: your authorised personal chat ID.

The repository is public, but Actions secrets are not exposed in repository source. Never put tokens in code, issues, logs or commits.

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
2. Cloudflare validates the Telegram webhook secret and authorised chat ID.
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
The dashboard uses a local CSV ledger under `data/recommendation_ledger.csv`. The GitHub Actions runner also writes to a temporary workspace; Actions cache may restore/save the universe files, but it is not a guaranteed permanent database for a trade ledger.

## Security
- Never commit `.env`, Telegram tokens or GitHub PATs.
- Rotate any token ever committed publicly.
- Restrict the Telegram bot to your personal chat ID.
- Use a fine-grained GitHub token with repository-only Actions write permission.


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

The NSE list is fetched from its public EQ CSV. BSE scrip-list refresh has returned HTTP 403 in this deployment; when so, the bot must report the failure and retain any existing cache. A BSE announcements feed is separate from the BSE scrip-master endpoint. Do not assume complete BSE universe coverage until refresh succeeds.

### Rotating universe
A 250-stock request selects up to 200 NSE plus 50 BSE-exclusive names; a 500-stock request selects up to 400 plus 100. The start point rotates by India calendar date, avoiding the prior alphabetical-first-symbol bias. A scan is a sample per request, not a simultaneous scan of all listed companies; price-fetch failures reduce coverage and are reported.

### Interpretation
The score is a transparent heuristic ranking, not a calibrated probability of profit or guaranteed prediction. The model still lacks a complete audited-fundamentals feed, official delivery-volume history, complete FII/DII flows, institutional order-book data and a full exchange-filings document parser. Entry, stop and target levels use the last available adjusted daily close and ATR; they are not live quotes or trade orders.

## Hosting clarification
Streamlit is optional and only hosts the visual dashboard. The Telegram workflow does not pass through Streamlit: Telegram -> Cloudflare Worker -> GitHub Actions -> Python scanner -> Telegram. GitHub Actions runs a temporary cloud runner only when a Telegram command dispatches a job.
