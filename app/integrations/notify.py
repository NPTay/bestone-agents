import logging
from typing import Literal

import httpx
from sqlalchemy import orm

from app import clock
from app.config import get_settings
from app.db.models import Alert

logger = logging.getLogger(__name__)

# httpx logs full request URLs at INFO, and the Telegram URL embeds the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)

AlertLevel = Literal["info", "warn", "urgent"]


def send_alert(db: orm.Session, level: AlertLevel, message: str) -> None:
    """Record an alert row and push it to Telegram when configured. Never raises."""
    settings = get_settings()
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_ADMIN_CHAT_ID
    use_telegram = bool(token and chat_id)
    alert = Alert(level=level, channel="telegram" if use_telegram else "db", message=message)
    db.add(alert)
    db.commit()
    if not use_telegram:
        return
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as exc:
        # Log only the exception type: httpx messages can include the URL (and bot token).
        logger.warning("Telegram alert delivery failed: %s", type(exc).__name__)
        return
    alert.delivered_at = clock.utcnow()
    db.commit()
