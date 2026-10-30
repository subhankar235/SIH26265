"""Core FDR / security deposit record."""
from datetime import date

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class FDR(Base):
    __tablename__ = 'fdrs'
    __table_args__ = (
        Index('ix_fdrs_status_maturity', 'status', 'maturity_date'),
        Index('ix_fdrs_dimensions', 'lifecycle_state', 'execution_state', 'authorization_state'),
        CheckConstraint(
            "lifecycle_state IS NULL OR lifecycle_state IN ('submitted','extraction_pending','extracting','validation_pending','validation_failed','correction_required','awaiting_institution','ready_for_scrutiny','under_review','awaiting_official_decision','accepted','renewal_required','renewed','release_requested','awaiting_release_decision','release_approved','release_rejected','escalated','expired','completed')",
            name='ck_fdr_lifecycle_state',
        ),
        CheckConstraint(
            "execution_state IS NULL OR execution_state IN ('not_started','running','waiting_event','waiting_timer','waiting_human','paused','retrying','failed','blocked','cancelled','completed')",
            name='ck_fdr_execution_state',
        ),
        CheckConstraint(
            "authorization_state IS NULL OR authorization_state IN ('not_required','pending','approved','rejected')",
            name='ck_fdr_authorization_state',
        ),
        CheckConstraint(
            "verification_level IS NULL OR verification_level IN ('declared','extracted','mock_verified','verified_external','ai_recommendation','human_scrutinized')",
            name='ck_fdr_verification_level',
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey('institutions.id'))
    fdr_number: Mapped[str] = mapped_column(String(50), index=True)
    bank_name: Mapped[str]
    branch: Mapped[str]
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    issue_date: Mapped[date]
    maturity_date: Mapped[date] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)  # FDRStatus
    lifecycle_state: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    # Denormalized read projection; workflow_instances is authoritative.
    execution_state: Mapped[str | None] = mapped_column(String(24), nullable=True, default='not_started', index=True)
    authorization_state: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    verification_level: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    # NULL denotes legacy rows whose provenance was never recorded; only explicit
    # false rows may be used as real historical data by ML Gate 0.
    is_synthetic: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, index=True)
    trust_badge: Mapped[str]  # TrustBadge
    declared_data: Mapped[dict] = mapped_column(JSON)  # institution self-declaration
    ocr_data: Mapped[dict | None] = mapped_column(JSON)
    bank_data: Mapped[dict | None] = mapped_column(JSON)
    last_alert_stage: Mapped[str | None]
    replaces_fdr_id: Mapped[int | None] = mapped_column(ForeignKey('fdrs.id'))
