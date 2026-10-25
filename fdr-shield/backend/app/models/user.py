"""Login account; role drives RBAC."""

from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Integer, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (Index('ix_users_role_status', 'role', 'status'),
        CheckConstraint("role IN ('institution','aicte_official','admin')", name='ck_users_role'),
        CheckConstraint("status IN ('invited','pending_email_verify','pending_approval','active','locked','disabled')", name='ck_users_status'),
        CheckConstraint("(role = 'institution' AND institution_id IS NOT NULL) OR (role <> 'institution' AND institution_id IS NULL)", name='ck_users_role_institution'))
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(nullable=True)
    role: Mapped[str]  # Role enum
    institution_id: Mapped[int | None] = mapped_column(ForeignKey('institutions.id'))
    totp_secret: Mapped[str | None]
    mfa_secret_enc: Mapped[str | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    full_name: Mapped[str] = mapped_column(String(255), default='')
    status: Mapped[str] = mapped_column(String(32), default='active', index=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc))
