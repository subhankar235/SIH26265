"""Login account; role drives RBAC."""

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, JSON, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str]
    role: Mapped[str]  # Role enum
    institution_id: Mapped[int | None] = mapped_column(ForeignKey('institutions.id'))
    totp_secret: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(default=True)
