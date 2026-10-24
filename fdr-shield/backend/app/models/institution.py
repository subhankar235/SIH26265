"""Technical institution registered with AICTE."""

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Institution(Base):
    __tablename__ = 'institutions'
    id: Mapped[int] = mapped_column(primary_key=True)
    aicte_id: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str]
    state: Mapped[str]
    head_name: Mapped[str]
    contact_email: Mapped[str]
    contact_phone: Mapped[str]
    telegram_chat_id: Mapped[str | None]
