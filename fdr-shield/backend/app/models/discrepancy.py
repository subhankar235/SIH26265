"""One mismatch between declared / OCR / bank values."""

from datetime import datetime, timezone
from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Discrepancy(Base):
    __tablename__ = 'discrepancies'
    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'))
    field: Mapped[str]  # amount | maturity_date | bank | fdr_number | holder
    declared_value: Mapped[str]
    extracted_value: Mapped[str]
    source: Mapped[str]  # ocr | bank_api
    severity: Mapped[str]  # low | high
    rule_id: Mapped[str | None] = mapped_column(nullable=True)
    rule_version: Mapped[str | None] = mapped_column(nullable=True)
    resolved: Mapped[bool] = mapped_column(default=False)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=utc_now)
