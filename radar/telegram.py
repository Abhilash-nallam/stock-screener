import os, requests
from dotenv import load_dotenv
load_dotenv()
def send_telegram(text):
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip(); chat=os.getenv("TELEGRAM_CHAT_ID","").strip()
    if not token or not chat: raise RuntimeError("Telegram bot token/chat ID missing in local .env")
    r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
       json={"chat_id":chat,"text":text,"disable_web_page_preview":True},timeout=20)
    r.raise_for_status(); return r.json()
