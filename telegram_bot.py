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
    """Compact, labelled stock card that fits naturally in Telegram."""
    symbol = html.escape(str(row.get("symbol", "—")))
    company = html.escape(str(row.get("company", "—")))
    exchange = html.escape(str(row.get("exchange", "NSE")).upper())
    try:
        score_value = float(row.get("score", 0))
        score = f"{score_value:.1f}/100" if math.isfinite(score_value) else "n/a"
    except (TypeError, ValueError):
        score = "n/a"

    news = _as_list(row.get("news"))
    flags = _as_list(row.get("news_flags"))
    reasons = _as_list(row.get("reasons"))

    lines = [
        f"<b>{rank}. {symbol} — {company}</b> ({exchange})",
        f"💰 <b>Last close:</b> {_money(row.get('price'))}   |   <b>Model rank:</b> {score}",
        f"📈 <b>Change:</b> 1D {_pct(row.get('change_1d_pct'))}  ·  5D {_pct(row.get('ret5_pct'))}  ·  20D {_pct(row.get('ret20_pct'))}",
        f"🎯 <b>Entry reference:</b> {_money(row.get('entry_low'))} – {_money(row.get('entry_high'))}",
        f"🛑 <b>Stop reference:</b> {_money(row.get('stop_loss'))}",
        f"🏁 <b>Targets:</b> T1 {_money(row.get('target1'))}  ·  T2 {_money(row.get('target2'))}",
        f"⚠️ <b>Risk:</b> {_risk(row.get('risk'))}  |  <b>RSI:</b> {_number(row.get('rsi'))}  |  <b>Rel. volume:</b> {_number(row.get('rvol'), 2)}x",
        f"🧭 <b>Status:</b> {html.escape(str(row.get('setup_status', 'Not assessed')))}",
    ]

    if reasons:
        reason_text = " • ".join(str(x) for x in reasons[:2])
        lines.append(f"🔎 <b>Why ranked:</b> {html.escape(reason_text[:260])}")
    if flags:
        lines.append(f"🚩 <b>Risk flags:</b> {html.escape('; '.join(str(x) for x in flags)[:220])}")
    if news:
        top = news[0]
        source = html.escape(str(top.get("publisher") or top.get("source") or "News"))
        title = html.escape(str(top.get("title") or "")[:180])
        date = html.escape(_headline_date(top))
        link = str(top.get("link") or "")
        if link.startswith(("https://", "http://")):
            lines.append(f"📰 <b>Relevant news ({date}):</b> <a href=\"{html.escape(link, quote=True)}\">{title}</a> · {source}")
        else:
            lines.append(f"📰 <b>Relevant news ({date}):</b> {title} · {source}")
    return "\n".join(lines)


def _benchmark_line(label, item):
    return (
        f"• <b>{html.escape(label)}:</b> "
        f"1D {_pct(item.get('daily_pct'))}  |  "
        f"5D {_pct(item.get('weekly_pct'))}  |  "
        f"20D {_pct(item.get('monthly_pct'))}"
    )


def _bucket_messages(title, rows):
    """Build one readable price-band message; split safely before Telegram's limit."""
    heading = f"<b>{title}</b>\n<i>Rank is a model score, not a probability of profit.</i>"
    if rows.empty:
        return [heading + "\n\n⚪ No stock in this price band passed all quality filters."]

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
    """Format a scan as distinct, compact Telegram messages."""
    market = result.get("market") or {}
    regime = str(market.get("regime", "unknown")).upper()
    regime_icon = "🟢" if regime == "BULLISH" else "🔴" if regime == "BEARISH" else "🟡"
    global_risk = str(market.get("global_risk", "unknown")).upper()
    global_icon = "🟢" if global_risk == "RISK_ON" else "🔴" if global_risk == "RISK_OFF" else "🟡"

    data_date = html.escape(str(result.get("data_date") or "unavailable"))
    selected = int(result.get("selected_count", 0) or 0)
    usable = int(result.get("success_count", 0) or 0)
    coverage = (100.0 * usable / selected) if selected else 0.0
    header_lines = [
        "<b>🇮🇳 INDIA STOCK RADAR — SCAN SUMMARY</b>",
        f"🗓 <b>Price data through:</b> {data_date} (last available daily close)",
        f"🇮🇳 <b>Nifty trend:</b> {regime_icon} {html.escape(regime)}",
        f"   Last session: {_pct(market.get('nifty_change_1d'))}  |  5 sessions: {_pct(market.get('nifty_change_5d'))}",
        f"🌍 <b>Global risk:</b> {global_icon} {html.escape(global_risk)} "
        f"({market.get('global_positive_count', 0)}/{market.get('global_count', 0)} global indices positive over 5 sessions)",
        f"🔎 <b>Universe scan:</b> {usable}/{selected} usable histories ({coverage:.1f}%)",
        f"   Selected: {result.get('nse_selected', 0)} NSE + {result.get('bse_selected', 0)} BSE",
        f"   Qualified watchlist candidates: {result.get('candidate_count', 0)}",
        f"📰 <b>Broad news feeds:</b> {result.get('news_count', 0)} headlines · "
        f"{result.get('news_sources_working', 0)}/{result.get('news_sources_total', 0)} sources responding",
        "<i>Company searches are separately run for the leading 35 technical candidates.</i>",
        "<i>Daily-close research only: levels are reference zones, not live orders. A higher model rank is not a profit probability or guarantee.</i>",
    ]
    messages = ["\n".join(header_lines)]

    benchmarks = market.get("benchmarks", {}) or {}
    india_lines = ["<b>🇮🇳 INDIA MARKET</b>"]
    india_lines.append(
        f"• <b>NIFTY 50 trend:</b> {html.escape(regime)} · "
        f"1D {_pct(market.get('nifty_change_1d'))} · 5D {_pct(market.get('nifty_change_5d'))}"
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

    market_sections = india_lines + [""] + global_lines + [""] + macro_lines
    messages.append("\n".join(market_sections))

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

    messages.extend(_bucket_messages("🟢 TOP CANDIDATES — PRICE ≤ ₹1,000", result["low"]))
    messages.extend(_bucket_messages("🔵 TOP CANDIDATES — PRICE > ₹1,000", result["high"]))
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
