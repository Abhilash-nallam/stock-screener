"""Telegram Bot API helpers shared by Streamlit and the long-polling worker."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
TIMEOUT_SECONDS = 25


def _read_secret(name):
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        import streamlit as st
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


def telegram_token():
    token = _read_secret("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from worker environment or Streamlit Secrets.")
    return token


def send_telegram(message, chat_id=None, parse_mode=None, reply_markup=None):
    token = telegram_token()
    target = str(chat_id or _read_secret("TELEGRAM_CHAT_ID")).strip()
    if not target:
        raise RuntimeError("TELEGRAM_CHAT_ID is missing.")
    payload = {"chat_id": target, "text": str(message), "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=TIMEOUT_SECONDS,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok or not isinstance(body, dict) or not body.get("ok"):
        description = body.get("description", "Unexpected Telegram response") if isinstance(body, dict) else "Invalid Telegram response"
        raise RuntimeError(f"Telegram send failed (HTTP {response.status_code}): {description}")
    return body


def telegram_api(method, payload=None, timeout=TIMEOUT_SECONDS):
    token = telegram_token()
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload or {},
        timeout=timeout,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok or not isinstance(body, dict) or not body.get("ok"):
        description = body.get("description", "Unexpected Telegram response") if isinstance(body, dict) else "Invalid Telegram response"
        raise RuntimeError(f"Telegram API {method} failed (HTTP {response.status_code}): {description}")
    return body.get("result")
