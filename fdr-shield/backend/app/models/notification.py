"""Alert dispatch history (also prevents duplicate sends)."""
from datetime import datetime

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Notification(Base):
    __tablename__ = 'notifications'
    __table_args__ = (UniqueConstraint('fdr_id','stage','channel',name='uq_notification_fdr_stage_channel'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'))
    stage: Mapped[str]  # AlertStage
    channel: Mapped[str]  # email | telegram | whatsapp_mock
    recipient: Mapped[str]
    status: Mapped[str]  # queued | sent | failed
    sent_at: Mapped[datetime | None]
