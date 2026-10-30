import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.enums import AccountStatus, Role
from app.core.exceptions import InvalidStateTransition, PermissionDenied
from app.core.security import verify_password
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.super_admin_setup import SuperAdminSetupRequest
from app.services import super_admin_setup_service


def setup_payload(email='root@example.test', secret='one-time-super-secret'):
    return SuperAdminSetupRequest(
        full_name='Initial Portal Owner', email=email, phone_number='+1 (202) 555-0164',
        password='Complex-Initial-Passphrase-2026!',
        confirm_password='Complex-Initial-Passphrase-2026!', setup_secret=secret,
    )


def test_super_admin_setup_secret_hash_phone_audit_and_permanent_close(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(super_admin_setup_service, 'get_settings',
            lambda: SimpleNamespace(super_admin_setup_secret='one-time-super-secret'))
        async with factory() as session:
            with pytest.raises(PermissionDenied, match='setup secret is invalid'):
                await super_admin_setup_service.register_initial_super_admin(
                    session, setup_payload(secret='wrong-secret'))
            with pytest.raises(InvalidStateTransition, match='confirmation do not match'):
                await super_admin_setup_service.register_initial_super_admin(session,
                    setup_payload().model_copy(update={'confirm_password':'Different-Confirmation-2026!'}))

            user = await super_admin_setup_service.register_initial_super_admin(session, setup_payload())
            await session.commit()
            assert user.role == Role.SUPER_ADMIN.value
            assert user.status == AccountStatus.ACTIVE.value and user.is_active
            assert user.phone_number == '+1 (202) 555-0164'
            assert user.password_hash != 'Complex-Initial-Passphrase-2026!'
            assert verify_password('Complex-Initial-Passphrase-2026!', user.password_hash)
            assert await session.scalar(select(func.count(AuditLog.id)).where(
                AuditLog.action == 'INITIAL_SUPER_ADMIN_REGISTERED')) == 1
            with pytest.raises(InvalidStateTransition, match='already been completed'):
                await super_admin_setup_service.register_initial_super_admin(
                    session, setup_payload(email='second@example.test'))
        await engine.dispose()
    asyncio.run(run())


def test_super_admin_setup_is_serialized_against_concurrent_first_registrations(tmp_path, monkeypatch):
    async def run():
        database = tmp_path / 'super-admin-bootstrap.db'
        engine = create_async_engine(f'sqlite+aiosqlite:///{database}',
            connect_args={'timeout': 10})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(super_admin_setup_service, 'get_settings',
            lambda: SimpleNamespace(super_admin_setup_secret='one-time-super-secret'))

        async def attempt(email):
            async with factory() as session:
                try:
                    await super_admin_setup_service.register_initial_super_admin(
                        session, setup_payload(email=email))
                    await session.commit()
                    return 'created'
                except InvalidStateTransition:
                    await session.rollback()
                    return 'closed'

        results = await asyncio.gather(attempt('first@example.test'), attempt('second@example.test'))
        async with factory() as session:
            count = await session.scalar(select(func.count(User.id)).where(User.role == Role.SUPER_ADMIN.value))
        assert sorted(results) == ['closed', 'created']
        assert count == 1
        await engine.dispose()
    asyncio.run(run())


def test_public_super_admin_setup_stays_closed_when_secret_is_unconfigured(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(super_admin_setup_service, 'get_settings',
            lambda: SimpleNamespace(super_admin_setup_secret=''))
        async with factory() as session:
            with pytest.raises(InvalidStateTransition, match='not configured'):
                await super_admin_setup_service.register_initial_super_admin(session, setup_payload())
        await engine.dispose()
    asyncio.run(run())
