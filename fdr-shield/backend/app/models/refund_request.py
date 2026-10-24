"""Discharge / refund workflow."""

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class RefundRequest(Base):
    __tablename__ = 'refund_requests'
    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'))
    requested_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str]  # pending | approved | rejected | released
    reviewed_by: Mapped[int | None]
    remarks: Mapped[str | None] = mapped_column(Text)
