"""Optional Telegram and Gmail alerts."""
import smtplib,requests
from email.mime.text import MIMEText
from config import TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID,SMTP_EMAIL,SMTP_PASSWORD,ALERT_EMAIL_TO
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[info] Telegram not configured, skipping");return False
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp=requests.post(url,data={"chat_id":TELEGRAM_CHAT_ID,"text":message},timeout=10)
        return resp.status_code==200
    except Exception as e:print(f"[warn] Telegram send failed: {e}");return False
def send_email(subject,body_markdown):
    if not SMTP_EMAIL or not SMTP_PASSWORD or not ALERT_EMAIL_TO:
        print("[info] Email not configured, skipping");return False
    msg=MIMEText(body_markdown,"plain");msg["Subject"]=subject;msg["From"]=SMTP_EMAIL;msg["To"]=ALERT_EMAIL_TO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as server:
            server.login(SMTP_EMAIL,SMTP_PASSWORD);server.sendmail(SMTP_EMAIL,ALERT_EMAIL_TO,msg.as_string())
        return True
    except Exception as e:print(f"[warn] Email send failed: {e}");return False
