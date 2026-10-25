"""One-time bootstrap for the first admin account; credentials are read from environment."""
import asyncio
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.core.enums import AccountStatus, Role
from app.core.security import hash_password
from app.models import User
from app.services.audit_service import record
from app.services.auth_service import validate_password_strength


async def main():
    settings = get_settings()
    email = settings.initial_admin_email.strip().lower()
    password = settings.initial_admin_password
    if not email or not password:
        raise SystemExit('Set INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD for the one-time bootstrap.')
    try:
        validate_password_strength(password, email, 'System Administrator')
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    await init_db()
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing:
            if existing.role != Role.ADMIN.value:
                raise SystemExit('The configured email already belongs to a non-admin account.')
            print('Admin account already exists; no change made.')
            return
        any_admin = await session.scalar(select(User.id).where(User.role == Role.ADMIN.value).limit(1))
        if any_admin:
            raise SystemExit('An Admin already exists. Create additional Admin accounts from the Admin portal.')
        user = User(email=email, full_name='System Administrator', password_hash=hash_password(password),
            role=Role.ADMIN.value, institution_id=None, status=AccountStatus.ACTIVE.value,
            is_active=True, must_change_password=True)
        session.add(user)
        await session.flush()
        await record(session, None, 'user', user.id, 'INITIAL_ADMIN_CREATED', 'system', {'role': [None, Role.ADMIN.value]})
        await session.commit()
        print('Initial Admin created. Remove INITIAL_ADMIN_PASSWORD from the environment now.')


if __name__ == '__main__':
    asyncio.run(main())
