"""Metadata of a file stored in S3/MinIO."""

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'))
    doc_type: Mapped[str]  # fdr_scan | pledge_letter | sanction_letter | refund_claim
    s3_key: Mapped[str]
    content_type: Mapped[str]
    uploaded_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
