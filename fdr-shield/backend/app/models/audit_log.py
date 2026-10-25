"""Append-only audit trail."""
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import event
from app.core.database import Base


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    __table_args__ = (Index('ix_audit_entity_id', 'entity', 'entity_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None]
    actor_type: Mapped[str] = mapped_column(String(16), default='user')
    institution_id: Mapped[int | None] = mapped_column(ForeignKey('institutions.id'), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entity: Mapped[str]
    entity_id: Mapped[int]
    action: Mapped[str]
    ip_address: Mapped[str]
    delta_changes: Mapped[dict] = mapped_column(JSON)  # {field: [old, new]}
    created_at: Mapped[datetime]  # append-only: NO update/delete paths exist


def _reject_audit_mutation(mapper, connection, target):
    raise RuntimeError('AuditLog is append-only; update/delete is forbidden.')


event.listen(AuditLog, 'before_update', _reject_audit_mutation)
event.listen(AuditLog, 'before_delete', _reject_audit_mutation)
