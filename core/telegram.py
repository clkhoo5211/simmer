import os
import requests
from loguru import logger
from core.store import load_credentials

def send_telegram_message(text: str) -> bool:
    """
    Send a message to a Telegram chat using a bot.
    Credentials are loaded from Redis (overlayed from environment falls back).
    """
    creds = load_credentials()
    
    bot_token = creds.get("telegram_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = creds.get("telegram_chat_id") or os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        logger.warning("Telegram notification skipped: Missing BOT_TOKEN or CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram notification sent successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False
