"""Outbound Telegram delivery for the Streamlit dashboard."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
TIMEOUT_SECONDS = 20


def _read_secret(name):
    """Read local .env/environment first, then Streamlit's native secrets."""
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        import streamlit as st
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


def send_telegram(message):
    token = _read_secret("TELEGRAM_BOT_TOKEN")
    chat_id = _read_secret("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        missing = []
        if not token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        raise RuntimeError(
            "Telegram configuration missing: " + ", ".join(missing) +
            ". Add these as root-level Streamlit Secrets and save/reboot the app."
        )

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": str(message),
            "disable_web_page_preview": True,
        },
        timeout=TIMEOUT_SECONDS,
    )

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok or not isinstance(payload, dict) or not payload.get("ok"):
        # Telegram's response contains a useful description; never expose the bot token.
        description = payload.get("description", "Telegram returned an unexpected response") if isinstance(payload, dict) else "Invalid Telegram response"
        raise RuntimeError(f"Telegram send failed (HTTP {response.status_code}): {description}")

    return payload
