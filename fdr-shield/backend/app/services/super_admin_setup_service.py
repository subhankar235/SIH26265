"""One-time public bootstrap for the initial Super Admin account."""
from __future__ import annotations

import hmac

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import AccountStatus, Role
from app.core.exceptions import InvalidStateTransition, PermissionDenied
from app.models.user import User
from app.schemas.super_admin_setup import SuperAdminSetupRequest
from app.services.audit_service import record
from app.services.auth_service import hash_password, utcnow, validate_password_strength

BOOTSTRAP_LOCK_ID = 741_326_501


async def acquire_bootstrap_lock(session: AsyncSession) -> None:
    """Serialize bootstrap against other setup requests and the CLI initializer."""
    dialect = session.get_bind().dialect.name
    if dialect == 'postgresql':
        await session.execute(text('SELECT pg_advisory_xact_lock(:lock_id)'),
                              {'lock_id': BOOTSTRAP_LOCK_ID})
    elif dialect == 'sqlite':
        await session.execute(text('BEGIN IMMEDIATE'))
    else:
        raise RuntimeError('Initial Super Admin bootstrap requires PostgreSQL or SQLite locking support.')


async def register_initial_super_admin(session: AsyncSession,
                                       data: SuperAdminSetupRequest) -> User:
    """Validate the private setup secret and create the only public Super Admin."""
    settings = get_settings()
    expected_secret = settings.super_admin_setup_secret
    if not expected_secret:
        raise InvalidStateTransition('Super Admin setup is not configured.')
    if not hmac.compare_digest(data.setup_secret.encode('utf-8'), expected_secret.encode('utf-8')):
        raise PermissionDenied('The Super Admin setup secret is invalid.')
    if data.password != data.confirm_password:
        raise InvalidStateTransition('Password and confirmation do not match.')

    email = str(data.email).strip().lower()
    validate_password_strength(data.password, email, data.full_name)
    password_hash = hash_password(data.password)

    await acquire_bootstrap_lock(session)
    existing_admin = await session.scalar(select(User.id).where(User.role == Role.SUPER_ADMIN.value).limit(1))
    if existing_admin:
        raise InvalidStateTransition('Initial Super Admin setup has already been completed.')
    if await session.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise InvalidStateTransition('This email cannot be used for initial Super Admin setup.')

    now = utcnow()
    user = User(email=email, full_name=data.full_name.strip(), phone_number=data.phone_number.strip(),
        password_hash=password_hash, role=Role.SUPER_ADMIN.value, institution_id=None,
        status=AccountStatus.ACTIVE.value, is_active=True, email_verified_at=now,
        created_at=now, updated_at=now)
    session.add(user)
    await session.flush()
    await record(session, None, 'user', user.id, 'INITIAL_SUPER_ADMIN_REGISTERED', 'system',
        {'role': [None, Role.SUPER_ADMIN.value], 'status': [None, AccountStatus.ACTIVE.value]})
    return user
