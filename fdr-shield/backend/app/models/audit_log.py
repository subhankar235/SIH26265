"""Append-only audit trail."""
from datetime import datetime

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    __table_args__ = (Index('ix_audit_entity_id', 'entity', 'entity_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None]
    entity: Mapped[str]
    entity_id: Mapped[int]
    action: Mapped[str]
    ip_address: Mapped[str]
    delta_changes: Mapped[dict] = mapped_column(JSON)  # {field: [old, new]}
    created_at: Mapped[datetime]  # append-only: NO update/delete paths exist
