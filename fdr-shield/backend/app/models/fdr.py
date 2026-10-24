"""Core FDR / security deposit record."""
from datetime import date

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class FDR(Base):
    __tablename__ = 'fdrs'
    __table_args__ = (Index('ix_fdrs_status_maturity', 'status', 'maturity_date'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey('institutions.id'))
    fdr_number: Mapped[str] = mapped_column(String(50), index=True)
    bank_name: Mapped[str]
    branch: Mapped[str]
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    issue_date: Mapped[date]
    maturity_date: Mapped[date] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)  # FDRStatus
    trust_badge: Mapped[str]  # TrustBadge
    declared_data: Mapped[dict] = mapped_column(JSON)  # institution self-declaration
    ocr_data: Mapped[dict | None] = mapped_column(JSON)
    bank_data: Mapped[dict | None] = mapped_column(JSON)
    last_alert_stage: Mapped[str | None]
    replaces_fdr_id: Mapped[int | None] = mapped_column(ForeignKey('fdrs.id'))
