"""Long-polling Telegram control bot. Run as a separate, always-on worker."""
import html
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
    text = str(value or "Unknown")
    if text.lower() == "high":
        return "🔴 High"
    if text.lower() == "moderate":
        return "🟡 Moderate"
    if text.lower() == "controlled":
        return "🟢 Controlled"
    return "⚪ " + html.escape(text)


def _money(value):
    try:
        number = float(value)
        if not math.isfinite(number):
            return "n/a"
        return f"₹{number:,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _stock_card(row, rank):
    symbol = html.escape(str(row.get("symbol", "")))
    company = html.escape(str(row.get("company", "")))
    score = float(row.get("score", 0))
    ret1 = _pct(row.get("change_1d_pct"))
    ret5 = _pct(row.get("ret5_pct"))
    ret20 = _pct(row.get("ret20_pct"))
    rvol = row.get("rvol")
    rvol_text = f"{float(rvol):.2f}x" if rvol is not None else "n/a"
    rsi = row.get("rsi")
    rsi_text = f"{float(rsi):.1f}" if rsi is not None else "n/a"
    entry = f"{_money(row.get('entry_low'))} – {_money(row.get('entry_high'))}"
    return (
        f"<b>{rank}. {symbol} | {company}</b>\n"
        f"💰 <b>{_money(row.get('price'))}</b>  ·  ⭐ Score <b>{score:.1f}/100</b>\n"
        f"📊 1D {ret1}   ·   5D {ret5}   ·   20D {ret20}\n"
        f"🎯 Entry reference: {entry}\n"
        f"🛑 Stop reference: <b>{_money(row.get('stop_loss'))}</b>\n"
        f"🏁 Targets: T1 <b>{_money(row.get('target1'))}</b>  ·  T2 <b>{_money(row.get('target2'))}</b>\n"
        f"⚠️ Risk: {_risk(row.get('risk'))}  ·  RSI {rsi_text}  ·  Rel.Vol {rvol_text}\n"
        f"🧭 Setup: {html.escape(str(row.get('setup_status', 'n/a')))}"
    )


def format_scan_messages(result):
    market = result["market"]
    regime = str(market.get("regime", "unknown")).upper()
    regime_icon = "🟢" if regime == "BULLISH" else "🔴" if regime == "BEARISH" else "🟡"
    date = html.escape(str(result.get("data_date") or "unavailable"))
    header = (
        "<b>🇮🇳 INDIA STOCK RADAR</b>\n"
        f"🗓 Data date: <b>{date}</b>\n"
        f"🌐 Nifty: {regime_icon} <b>{html.escape(regime)}</b>  ·  "
        f"1D {_pct(market.get('nifty_change_1d'))}  ·  5D {_pct(market.get('nifty_change_5d'))}\n"
        f"🔎 Scan: {result['success_count']}/{result['selected_count']} histories usable "
        f"· {result['candidate_count']} passed candidate filters\n"
        "<i>Daily-close research only. Levels are references, not live prices or orders.</i>"
    )
    messages = [header]
    for title, key in [("🟢 TOP CANDIDATES · PRICE ≤ ₹1,000", "low"),
                       ("🔵 TOP CANDIDATES · PRICE > ₹1,000", "high")]:
        rows = result[key]
        parts = [f"<b>{title}</b>"]
        if rows.empty:
            parts.append("<i>No stock in this price band passed the filters.</i>")
        else:
            for rank, (_, row) in enumerate(rows.iterrows(), 1):
                parts.append(_stock_card(row, rank))
        messages.append("\n\n".join(parts))
    messages.append(
        "<i>🟢/🔴 mark positive/negative percentage moves. Telegram does not support "
        "arbitrary coloured text; the icons provide the colour cue. Verify company filings and quotes.</i>"
    )
    return messages


def show_menu(chat_id, greeting=True):
    text = (
        "<b>India Stock Radar Bot</b>\n"
        "Choose an action below. You can scan 250 or 500 stocks directly from Telegram.\n\n"
        "Commands: /fetch 250, /fetch 500, /scan 250, /refresh_nse, /refresh_bse, /refresh_all, /status, /help"
    ) if greeting else "Choose your scan size:"
    send_telegram(text, chat_id=chat_id, parse_mode="HTML", reply_markup=MENU)


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
        send_telegram(_status_text(), chat_id=chat_id, parse_mode="HTML")
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
        send_telegram(_status_text(), chat_id=chat_id, parse_mode="HTML")
    elif data == "help":
        show_menu(chat_id, greeting=True)


def main():
    if not _read_secret("TELEGRAM_CHAT_ID"):
        raise RuntimeError("Set TELEGRAM_CHAT_ID to your own private Telegram chat ID before starting the bot.")
    _load_offset()
    # This worker uses long polling; remove any webhook left over from a previous setup.
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
