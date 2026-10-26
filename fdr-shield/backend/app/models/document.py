"""Metadata of a file stored in S3/MinIO."""

from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Document(Base):
    __tablename__ = 'documents'
    __table_args__ = (Index('ix_documents_fdr_type_version', 'fdr_id', 'doc_type', 'version_no'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'))
    doc_type: Mapped[str]  # fdr_scan | pledge_letter | sanction_letter | refund_claim
    s3_key: Mapped[str]
    content_type: Mapped[str]
    uploaded_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supersedes_document_id: Mapped[int | None] = mapped_column(ForeignKey('documents.id'), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
