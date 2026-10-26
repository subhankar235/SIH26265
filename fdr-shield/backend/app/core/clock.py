"""Business-date helpers with an explicit configured timezone (default Asia/Kolkata)."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from app.core.config import get_settings


def business_today(now: datetime | None=None) -> date:
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
    return current.astimezone(ZoneInfo(get_settings().rules_default_tz)).date()
