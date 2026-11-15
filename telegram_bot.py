"""Telegram stock-radar reporting and command interface."""
import html
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from radar.scan_service import refresh_exchange, refresh_both, run_scan, universe_status
from radar.telegram import send_telegram, telegram_api, _read_secret

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("india-stock-radar-bot")
STATE_PATH = Path("data/telegram_bot_state.json")
SCAN_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-scan")
BUSY = threading.Lock()
OFFSET = 0

MENU = {
    "inline_keyboard": [
        [
            {"text": "🚀 Fetch 250 stocks", "callback_data": "scan:250"},
            {"text": "🚀 Fetch 500 stocks", "callback_data": "scan:500"},
        ],
        [
            {"text": "🔄 Refresh NSE", "callback_data": "refresh:nse"},
            {"text": "🔄 Refresh BSE", "callback_data": "refresh:bse"},
        ],
        [{"text": "🔄 Refresh NSE + BSE", "callback_data": "refresh:both"}],
        [{"text": "📋 Universe status", "callback_data": "status"}],
        [{"text": "❔ Help", "callback_data": "help"}],
    ]
}


def allowed_chat_ids():
    ids = set()
    primary = _read_secret("TELEGRAM_CHAT_ID")
    if primary:
        ids.add(str(primary).strip())
    extra = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
    ids.update(x.strip() for x in extra.split(",") if x.strip())
    return ids


def _load_offset():
    global OFFSET
    try:
        if STATE_PATH.exists():
            OFFSET = int(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("offset", 0))
    except Exception:
        OFFSET = 0


def _save_offset():
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"offset": OFFSET}), encoding="utf-8")
    except Exception as exc:
        log.warning("Could not persist Telegram update offset: %s", exc)


def _pct(value):
    try:
        number = float(value)
        if not math.isfinite(number):
            return "⚪ n/a"
    except (TypeError, ValueError):
        return "⚪ n/a"
    return f"{'🟢' if number > 0 else '🔴' if number < 0 else '⚪'} {number:+.2f}%"


def _risk(value):
    text_value = str(value or "Unknown")
    if text_value.lower() == "high":
        return "🔴 High"
    if text_value.lower() == "moderate":
        return "🟡 Moderate"
    if text_value.lower() == "controlled":
        return "🟢 Controlled"
    return "⚪ " + html.escape(text_value)


def _money(value):
    try:
        number = float(value)
        if not math.isfinite(number):
            return "n/a"
        return f"₹{number:,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _as_list(value):
    return value if isinstance(value, (list, tuple)) else []

def _number(value, decimals=1):
    try:
        number = float(value)
        if not math.isfinite(number):
            return "n/a"
        return f"{number:.{decimals}f}"
    except (TypeError, ValueError):
        return "n/a"


def _headline_date(item):
    published = str(item.get("published") or "")
    return published[:10] if len(published) >= 10 and published[:4].isdigit() else "date n/a"


def _stock_card(row, rank):
    """Readable live-confirmed card; daily close is context, never the live entry."""
    symbol = html.escape(str(row.get("symbol", "—")))
    company = html.escape(str(row.get("company", "—")))
    exchange = html.escape(str(row.get("exchange", "NSE")).upper())
    daily_score = _number(row.get("score"), 1)
    live_score = _number(row.get("live_score"), 1)
    live_price = row.get("live_price")
    live_status = html.escape(str(row.get("live_status", "WAIT")))
    live_time = html.escape(str(row.get("live_quote_time", "unavailable")))
    quote_age = row.get("live_quote_age_seconds")

    news = _as_list(row.get("news"))
    flags = _as_list(row.get("news_flags"))
    lines = [
        f"<b>{rank}. {symbol} — {company}</b> ({exchange})",
        f"💹 <b>LIVE price:</b> {_money(live_price)}  ·  <b>Live score:</b> {live_score}/100",
        f"   Previous completed close: {_money(row.get('price'))}  ·  Last trade: {live_time}",
        f"📈 <b>Today:</b> {_pct(row.get('live_change_pct'))}  ·  Opening gap: {_pct(row.get('live_gap_pct'))}  ·  From open: {_pct(row.get('live_intraday_pct'))}",
        f"🧭 <b>Intraday:</b> VWAP {_money(row.get('live_vwap'))} ({_pct(row.get('live_vwap_distance_pct'))})  ·  3-bar 5m momentum {_pct(row.get('live_5m_momentum_pct'))}",
        f"🌐 <b>Relative to Nifty:</b> {_pct(row.get('live_relative_strength_pct'))}  ·  5D {_pct(row.get('ret5_pct'))}  ·  20D {_pct(row.get('ret20_pct'))}",
        f"🎯 <b>Entry zone:</b> {_money(row.get('live_entry_low'))} – {_money(row.get('live_entry_high'))}",
        f"🛑 <b>Stop:</b> {_money(row.get('live_stop'))}  ·  🏁 <b>Targets:</b> T1 {_money(row.get('live_target1'))}  ·  T2 {_money(row.get('live_target2'))}",
        f"⚠️ <b>Risk:</b> {_risk(row.get('risk'))}  ·  RSI {_number(row.get('rsi'))}  ·  ATR {_number(row.get('atr_pct'), 2)}%",
        f"🟢 <b>Decision:</b> {live_status}",
        f"⏱ <b>Quote age:</b> {_number(quote_age, 0)} sec  ·  <b>Daily score:</b> {daily_score}/100",
    ]
    reason = str(row.get("live_reason") or "")
    if reason:
        lines.append(f"🔎 <b>Confirmation:</b> {html.escape(reason[:240])}")
    if flags:
        lines.append(f"🚩 <b>Daily risk flags:</b> {html.escape('; '.join(str(x) for x in flags)[:180])}")
    if news:
        top = news[0]
        source = html.escape(str(top.get("publisher") or top.get("source") or "News"))
        title = html.escape(str(top.get("title") or "")[:160])
        date = html.escape(_headline_date(top))
        link = str(top.get("link") or "")
        if link.startswith(("https://", "http://")):
            lines.append(f"📰 <b>Company news ({date}):</b> <a href=\"{html.escape(link, quote=True)}\">{title}</a> · {source}")
        else:
            lines.append(f"📰 <b>Company news ({date}):</b> {title} · {source}")
    return "\n".join(lines)


def _benchmark_line(label, item):
    return (
        f"• <b>{html.escape(label)}:</b> "
        f"1D {_pct(item.get('daily_pct'))}  |  "
        f"5D {_pct(item.get('weekly_pct'))}  |  "
        f"20D {_pct(item.get('monthly_pct'))}"
    )


def _bucket_messages(title, rows):
    """Build one readable live price-band message; split safely before Telegram's limit."""
    heading = f"<b>{title}</b>\n<i>Only live-confirmed watchlist candidates are shown; no automatic orders.</i>"
    if rows.empty:
        return [heading + "\n\n⚪ No stock in this band passed the live confirmation gates. Wait or re-scan later."]

    messages = []
    current = heading
    for rank, (_, row) in enumerate(rows.iterrows(), 1):
        card = _stock_card(row, rank)
        proposed = current + "\n\n━━━━━━━━━━━━━━━━━━\n\n" + card
        if len(proposed) > 3500 and current != heading:
            messages.append(current)
            current = heading + " (continued)"
            proposed = current + "\n\n━━━━━━━━━━━━━━━━━━\n\n" + card
        current = proposed
    messages.append(current)
    return messages


def format_scan_messages(result):
    """Format market state or a live-confirmed report; never call daily-only picks live."""
    session = result.get("market_session") or {}
    phase = str(session.get("phase", "unknown"))
    if phase != "open":
        from radar.market_clock import format_market_status
        return [format_market_status(session)]

    if not result.get("live_ready", False):
        reason = html.escape(str(result.get("live_error") or "Live market data is unavailable.")[:900])
        return [
            "<b>🟠 INDIA STOCK RADAR — LIVE SCAN BLOCKED</b>\n"
            f"🟢 NSE session: <b>OPEN</b> ({html.escape(str(session.get('local_time', '')))} IST)\n"
            "No stock recommendations were generated because a reliable live-data check did not complete.\n\n"
            f"<b>Reason:</b> {reason}\n\n"
            "<b>Setup needed:</b> Add Groww API credentials as GitHub Actions secrets: "
            "<code>GROWW_ACCESS_TOKEN</code>, or <code>GROWW_API_KEY</code> and <code>GROWW_API_SECRET</code>.\n"
            "Groww's API-key/secret flow requires daily approval on its Cloud API Keys page. "
            "A manually generated access token expires daily at 06:00 IST.\n"
            "<i>Yahoo daily prices are not substituted for live quotes.</i>"
        ]

    market = result.get("market") or {}
    regime = str(market.get("regime", "unknown")).upper()
    regime_icon = "🟢" if regime == "BULLISH" else "🔴" if regime == "BEARISH" else "🟡"
    global_risk = str(market.get("global_risk", "unknown")).upper()
    global_icon = "🟢" if global_risk == "RISK_ON" else "🔴" if global_risk == "RISK_OFF" else "🟡"

    data_date = html.escape(str(result.get("data_date") or "unavailable"))
    selected = int(result.get("selected_count", 0) or 0)
    usable = int(result.get("success_count", 0) or 0)
    daily_coverage = (100.0 * usable / selected) if selected else 0.0
    breadth = result.get("live_breadth") or {}
    header_lines = [
        "<b>🇮🇳 INDIA STOCK RADAR — LIVE SCAN</b>",
        f"🟢 <b>NSE session:</b> OPEN · {html.escape(str(session.get('local_time', '')))} IST",
        f"⏱ <b>Live provider:</b> Groww Live Data API · quote coverage {result.get('live_coverage_pct', 0):.1f}% "
        f"({result.get('live_coverage_count', 0)}/{result.get('live_coverage_total', 0)} NSE stocks)",
        f"🗓 <b>Technical baseline:</b> completed daily close through {data_date} (today's unfinished daily bar excluded)",
        f"🇮🇳 <b>Nifty LIVE:</b> {_pct(result.get('live_nifty_change_pct'))} vs previous close · "
        f"daily trend {regime_icon} {html.escape(regime)}",
        f"📊 <b>Live breadth:</b> 🟢 {breadth.get('advances', 0)} advances · 🔴 {breadth.get('declines', 0)} declines · "
        f"⚪ {breadth.get('unchanged', 0)} unchanged",
        f"🌍 <b>Global risk:</b> {global_icon} {html.escape(global_risk)} "
        f"({market.get('global_positive_count', 0)}/{market.get('global_count', 0)} global indices positive over 5 sessions)",
        f"🔎 <b>Daily universe:</b> {usable}/{selected} usable histories ({daily_coverage:.1f}%) · "
        f"{result.get('nse_selected', 0)} NSE + {result.get('bse_selected', 0)} BSE selected",
        "⚠️ <b>BSE live coverage:</b> Not enabled yet; live-confirmed picks are NSE only. BSE scrip-code mapping is still required.",
        f"🧪 <b>Intraday checks:</b> {result.get('live_researched_count', 0)} leaders researched · "
        f"{result.get('live_confirmed_count', 0)} confirmed · {result.get('live_wait_count', 0)} waiting",
        f"📰 <b>Broad news feeds:</b> {result.get('news_count', 0)} headlines · "
        f"{result.get('news_sources_working', 0)}/{result.get('news_sources_total', 0)} sources responding",
        "<i>Signals require a fresh trade timestamp, live quote, VWAP and completed 5-minute candles. "
        "This is a watchlist, not a buy/sell order or profit guarantee.</i>",
    ]
    messages = ["\n".join(header_lines)]

    benchmarks = market.get("benchmarks", {}) or {}
    india_lines = ["<b>🇮🇳 INDIA MARKET</b>"]
    india_lines.append(
        f"• <b>NIFTY 50 LIVE:</b> {_pct(result.get('live_nifty_change_pct'))} vs previous close · "
        f"daily trend {html.escape(regime)}"
    )
    for key, label in (("SENSEX", "SENSEX"), ("INDIA_VIX", "India VIX")):
        if key in benchmarks:
            india_lines.append(_benchmark_line(label, benchmarks[key]))

    global_names = [
        ("SP500", "S&P 500"), ("NASDAQ", "Nasdaq"), ("DOW", "Dow Jones"),
        ("FTSE", "FTSE"), ("NIKKEI", "Nikkei"), ("HANG_SENG", "Hang Seng"),
    ]
    global_lines = ["<b>🌎 GLOBAL EQUITY MARKETS</b>"]
    for key, label in global_names:
        if key in benchmarks:
            global_lines.append(_benchmark_line(label, benchmarks[key]))

    macro_lines = ["<b>💹 MACRO WATCH</b>"]
    for key, label in (("USDINR", "USD/INR"), ("BRENT", "Brent crude"), ("GOLD", "Gold")):
        if key in benchmarks:
            macro_lines.append(_benchmark_line(label, benchmarks[key]))

    messages.append("\n".join(india_lines + [""] + global_lines + [""] + macro_lines))

    headline_lines = ["<b>📰 RELEVANT NEWS & OFFICIAL UPDATES</b>"]
    for title, key in (("Global market headlines", "global_news"),
                       ("Indian exchange / regulator updates", "official_news")):
        items = _as_list(result.get(key))[:5]
        headline_lines.append(f"\n<b>{title}</b>")
        if not items:
            headline_lines.append("⚪ No relevant headlines returned by the configured feeds.")
            continue
        for item in items:
            text = html.escape(str(item.get("title") or "")[:170])
            source = html.escape(str(item.get("publisher") or item.get("source") or "Source"))
            date = html.escape(_headline_date(item))
            link = str(item.get("link") or "")
            if link.startswith(("https://", "http://")):
                headline_lines.append(f"• <a href=\"{html.escape(link, quote=True)}\">{text}</a> — {source} · {date}")
            else:
                headline_lines.append(f"• {text} — {source} · {date}")
    messages.append("\n".join(headline_lines))

    messages.extend(_bucket_messages("🟢 LIVE-CONFIRMED CANDIDATES — PRICE ≤ ₹1,000", result["low"]))
    messages.extend(_bucket_messages("🔵 LIVE-CONFIRMED CANDIDATES — PRICE > ₹1,000", result["high"]))
    return messages

def show_menu(chat_id, greeting=True):
    message = (
        "<b>India Stock Radar Bot</b>\n"
        "Choose an action below. Scans run on GitHub Actions and return here.\n\n"
        "Commands: /fetch 250, /fetch 500, /refresh_nse, /refresh_bse, /refresh_all, /status, /help"
    ) if greeting else "Choose your scan size:"
    send_telegram(message, chat_id=chat_id, parse_mode="HTML", reply_markup=MENU)


def _start_scan(chat_id, limit):
    if limit not in (250, 500):
        send_telegram("Choose 250 or 500 stocks.", chat_id=chat_id)
        return
    if not BUSY.acquire(blocking=False):
        send_telegram("⏳ A scan or refresh is already running. Please try again shortly.", chat_id=chat_id)
        return
    send_telegram(
        f"⏳ <b>{limit}-stock scan started.</b>\n"
        "I am downloading daily price history, checking the market and researching leading headlines. "
        "The completed report will arrive here automatically.",
        chat_id=chat_id, parse_mode="HTML"
    )
    SCAN_POOL.submit(_scan_task, chat_id, limit)


def _scan_task(chat_id, limit):
    try:
        result = run_scan(limit=limit)
        for message in format_scan_messages(result):
            send_telegram(message, chat_id=chat_id, parse_mode="HTML")
    except Exception as exc:
        log.exception("Scan failed")
        send_telegram(
            "❌ <b>Scan failed</b>\n" + html.escape(str(exc)[:1200]),
            chat_id=chat_id, parse_mode="HTML"
        )
    finally:
        BUSY.release()


def _start_refresh(chat_id, exchange):
    if not BUSY.acquire(blocking=False):
        send_telegram("⏳ A scan or refresh is already running. Please try again shortly.", chat_id=chat_id)
        return
    send_telegram("🔄 Refresh started. I will report the result here.", chat_id=chat_id)
    SCAN_POOL.submit(_refresh_task, chat_id, exchange)


def _refresh_task(chat_id, exchange):
    try:
        if exchange == "both":
            result = refresh_both()
            lines = ["<b>Exchange universe refresh</b>"]
            for name in ("nse", "bse"):
                item = result["refreshed"].get(name)
                error = result["errors"].get(name)
                if item:
                    lines.append(f"🟢 {name.upper()}: {item['count']:,} securities refreshed")
                else:
                    lines.append(f"🔴 {name.upper()}: {html.escape(error or 'Refresh failed')}")
            send_telegram("\n".join(lines), chat_id=chat_id, parse_mode="HTML")
        else:
            result = refresh_exchange(exchange)
            send_telegram(
                f"🟢 <b>{result['exchange']} universe refreshed</b>\n"
                f"Active equity records cached: <b>{result['count']:,}</b>",
                chat_id=chat_id, parse_mode="HTML"
            )
    except Exception as exc:
        log.exception("Universe refresh failed")
        send_telegram("❌ Refresh failed: " + html.escape(str(exc)[:1200]), chat_id=chat_id, parse_mode="HTML")
    finally:
        BUSY.release()


def _status_text():
    counts = universe_status()
    return (
        "<b>Exchange universe status</b>\n"
        f"🇮🇳 NSE cached records: <b>{counts['nse']:,}</b>\n"
        f"🏛 BSE cached records: <b>{counts['bse']:,}</b>\n"
        f"🌐 Combined unique records: <b>{counts['combined']:,}</b>"
    )


def handle_message(message):
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    if chat_id not in allowed_chat_ids():
        log.warning("Ignored command from non-authorised chat id")
        return
    raw = str(message.get("text", "")).strip()
    if not raw:
        return
    parts = raw.split()
    command = parts[0].split("@", 1)[0].lower()
    if command in ("/start", "/help"):
        show_menu(chat_id, greeting=True)
    elif command in ("/scan", "/fetch"):
        if len(parts) > 1:
            try:
                _start_scan(chat_id, int(parts[1]))
            except ValueError:
                send_telegram("Usage: /scan 250 or /scan 500", chat_id=chat_id)
        else:
            show_menu(chat_id, greeting=False)
    elif command == "/refresh_nse":
        _start_refresh(chat_id, "nse")
    elif command == "/refresh_bse":
        _start_refresh(chat_id, "bse")
    elif command in ("/refresh_all", "/refresh"):
        _start_refresh(chat_id, "both")
    elif command in ("/status", "/universe"):
        send_telegram(_status_text(), chat_id=chat_id)
    elif command == "/menu":
        show_menu(chat_id, greeting=True)
    else:
        send_telegram("I did not recognise that command. Send /help for available controls.", chat_id=chat_id)


def handle_callback(callback):
    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    callback_id = callback.get("id")
    if chat_id not in allowed_chat_ids():
        if callback_id:
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Not authorised"})
        return
    data = str(callback.get("data", ""))
    if callback_id:
        telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Request received"})
    if data.startswith("scan:"):
        try:
            _start_scan(chat_id, int(data.split(":", 1)[1]))
        except ValueError:
            send_telegram("Choose 250 or 500 stocks.", chat_id=chat_id)
    elif data.startswith("refresh:"):
        _start_refresh(chat_id, data.split(":", 1)[1])
    elif data == "status":
        send_telegram(_status_text(), chat_id=chat_id)
    elif data == "help":
        show_menu(chat_id, greeting=True)


def main():
    if not _read_secret("TELEGRAM_CHAT_ID"):
        raise RuntimeError("Set TELEGRAM_CHAT_ID to your own private Telegram chat ID before starting the bot.")
    _load_offset()
    # Long-polling worker only; the Cloudflare webhook deployment is separate.
    telegram_api("deleteWebhook", {"drop_pending_updates": False})
    telegram_api("setMyCommands", {"commands": [
        {"command": "start", "description": "Open the stock radar menu"},
        {"command": "scan", "description": "Choose /scan 250 or /scan 500"},
        {"command": "fetch", "description": "Fetch a 250- or 500-stock report"},
        {"command": "refresh_nse", "description": "Refresh NSE equity universe"},
        {"command": "refresh_bse", "description": "Refresh BSE equity universe"},
        {"command": "refresh_all", "description": "Refresh NSE and BSE"},
        {"command": "status", "description": "Show cached exchange universe counts"},
        {"command": "universe", "description": "Show cached exchange universe counts"},
        {"command": "menu", "description": "Open scan and refresh buttons"},
        {"command": "help", "description": "Show bot controls"},
    ]})
    log.info("India Stock Radar Telegram worker started")
    global OFFSET
    while True:
        try:
            params = {"timeout": 40, "limit": 100, "allowed_updates": json.dumps(["message", "callback_query"])}
            if OFFSET:
                params["offset"] = OFFSET
            token = _read_secret("TELEGRAM_BOT_TOKEN")
            import requests
            response = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params=params,
                timeout=50,
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                raise RuntimeError(body.get("description", "getUpdates failed"))
            for update in body.get("result", []):
                OFFSET = max(OFFSET, int(update["update_id"]) + 1)
                _save_offset()
                try:
                    if "message" in update:
                        handle_message(update["message"])
                    elif "callback_query" in update:
                        handle_callback(update["callback_query"])
                except Exception:
                    log.exception("Failed to process Telegram update")
        except Exception as exc:
            log.exception("Telegram polling error: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
