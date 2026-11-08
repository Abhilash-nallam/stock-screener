import os
TELEGRAM_BOT_TOKEN=os.environ.get("TELEGRAM_BOT_TOKEN","")
TELEGRAM_CHAT_ID=os.environ.get("TELEGRAM_CHAT_ID","")
SMTP_EMAIL=os.environ.get("SMTP_EMAIL","")
SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD","")
ALERT_EMAIL_TO=os.environ.get("ALERT_EMAIL_TO","")
MIN_MARKET_CAP_CR=500
MIN_AVG_VOLUME=100_000
WEIGHTS={"fundamental":25,"valuation":20,"technical":25,"momentum":15,"risk":15}
MIN_ROE=12.0
MAX_DEBT_TO_EQUITY=1.0
RSI_OVERBOUGHT=75
RSI_OVERSOLD=30
TOP_N=5
REPORT_DIR="reports"
