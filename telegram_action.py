"""Entry point for scan/refresh jobs dispatched by the Telegram webhook."""
import html
import os
import sys
import traceback

from radar.scan_service import refresh_both, refresh_exchange, run_scan, universe_status
from radar.telegram import send_telegram
from telegram_bot import format_scan_messages


def execute(command, stock_limit, chat_id):
    if command == "scan":
        if stock_limit not in ("250", "500"):
            raise ValueError("Stock limit must be 250 or 500.")
        result = run_scan(limit=int(stock_limit), min_score=60, news_limit=6, workers=6)
        for message in format_scan_messages(result):
            send_telegram(message, chat_id=chat_id, parse_mode="HTML")
        return

    if command in ("refresh_nse", "refresh_bse"):
        exchange = "nse" if command.endswith("nse") else "bse"
        result = refresh_exchange(exchange)
        send_telegram(
            f"🟢 <b>{result['exchange']} universe refreshed</b>\n"
            f"Active equity records cached: <b>{result['count']:,}</b>",
            chat_id=chat_id,
            parse_mode="HTML",
        )
        return

    if command == "refresh_all":
        result = refresh_both()
        lines = ["<b>EXCHANGE UNIVERSE REFRESH</b>"]
        for exchange in ("nse", "bse"):
            item = result["refreshed"].get(exchange)
            error = result["errors"].get(exchange)
            if item:
                lines.append(f"🟢 {exchange.upper()}: <b>{item['count']:,}</b> securities refreshed")
            else:
                lines.append(f"🔴 {exchange.upper()}: {html.escape(str(error or 'Refresh failed'))}")
        send_telegram("\n".join(lines), chat_id=chat_id, parse_mode="HTML")
        return

    if command == "status":
        counts = universe_status()
        send_telegram(
            "<b>EXCHANGE UNIVERSE STATUS</b>\n"
            f"🇮🇳 NSE cached: <b>{counts['nse']:,}</b>\n"
            f"🏛 BSE cached: <b>{counts['bse']:,}</b>\n"
            f"🌐 Combined unique: <b>{counts['combined']:,}</b>",
            chat_id=chat_id,
            parse_mode="HTML",
        )
        return

    raise ValueError(f"Unsupported Telegram action: {command}")


def main():
    command = os.getenv("RADAR_COMMAND", "").strip()
    stock_limit = os.getenv("RADAR_STOCK_LIMIT", "250").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not chat_id:
        raise RuntimeError("Repository secret TELEGRAM_CHAT_ID is missing.")
    if not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        raise RuntimeError("Repository secret TELEGRAM_BOT_TOKEN is missing.")

    try:
        execute(command, stock_limit, chat_id)
    except Exception as exc:
        print("Telegram radar action failed:", repr(exc), file=sys.stderr)
        traceback.print_exc()
        # Inform the authorised user even when a scan or exchange endpoint fails.
        try:
            safe_message = html.escape(str(exc)[:1000])
            send_telegram(
                "❌ <b>INDIA STOCK RADAR — request failed</b>\n" + safe_message +
                "\n\nNo recommendation report was generated. Check the GitHub Actions log for details.",
                chat_id=chat_id,
                parse_mode="HTML",
            )
        except Exception as notify_exc:
            print("Could not notify Telegram chat:", repr(notify_exc), file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
