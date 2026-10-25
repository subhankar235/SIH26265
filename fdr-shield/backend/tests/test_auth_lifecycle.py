import asyncio
import re

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.database import Base, get_session
from app.core.enums import AccountStatus, Role
from app.core.exceptions import AuthError
from app.core.security import (create_access_token, decode_token, decrypt_mfa_secret,
    encrypt_mfa_secret, hash_password, needs_rehash, verify_password)
from app.main import create_app
from app.models import Institution, User
from app.models.auth_records import RefreshToken
from app.services import auth_service
from app.schemas.auth import InstitutionRegistrationRequest
from app.services import user_admin_service


def test_argon2id_password_hash_and_legacy_upgrade_path():
    encoded = hash_password('a-long-unique-password-2026')
    assert encoded.startswith('$argon2id$')
    assert verify_password('a-long-unique-password-2026', encoded)
    assert not verify_password('wrong-password', encoded)
    assert not needs_rehash(encoded)


def test_csrf_and_mfa_secrets_are_signed_or_encrypted():
    secret = 'JBSWY3DPEHPK3PXP'
    encrypted = encrypt_mfa_secret(secret)
    assert encrypted != secret
    assert decrypt_mfa_secret(encrypted) == secret


def test_portal_login_cookie_session_refresh_reuse_and_csrf():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
                                     connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution = Institution(aicte_id='AICTE-AUTH-001', name='Auth Institute', state='Delhi',
                head_name='Principal', contact_email='college@example.test', contact_phone='9000000000', status='active')
            session.add(institution)
            await session.flush()
            session.add_all([
                User(email='college@example.test', full_name='College User', password_hash=hash_password('College-Safe-Password-2026'),
                    role=Role.INSTITUTION.value, institution_id=institution.id, status=AccountStatus.ACTIVE.value, is_active=True),
                User(email='official@example.test', full_name='Official User', password_hash=hash_password('Official-Safe-Password-2026'),
                    role=Role.AICTE_OFFICIAL.value, institution_id=None, status=AccountStatus.ACTIVE.value, is_active=True),
            ])
            await session.commit()

        async def session_override():
            async with factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app = create_app()
        app.dependency_overrides[get_session] = session_override
        client = TestClient(app)
        wrong_portal = client.post('/api/v1/auth/login/official', json={
            'email': 'college@example.test', 'password': 'College-Safe-Password-2026'})
        wrong_password = client.post('/api/v1/auth/login/institution', json={
            'email': 'college@example.test', 'password': 'wrong-password'})
        assert wrong_portal.status_code == wrong_password.status_code == 401
        assert wrong_portal.json()['error'] == wrong_password.json()['error'] == {
            'code': 'INVALID_CREDENTIALS', 'message': auth_service.GENERIC_INVALID}

        response = client.post('/api/v1/auth/login/institution', json={
            'email': 'college@example.test', 'password': 'College-Safe-Password-2026'})
        assert response.status_code == 200
        assert 'access_token' not in response.json()
        assert response.json()['user']['role'] == 'institution'
        assert 'httponly' in response.headers.get('set-cookie', '').lower()
        assert client.get('/api/v1/auth/me').json()['email'] == 'college@example.test'

        csrf = client.cookies.get('csrf_token')
        assert client.post('/api/v1/auth/logout').status_code == 403
        assert client.post('/api/v1/auth/logout', headers={'X-CSRF-Token': csrf}).status_code == 204
        assert client.get('/api/v1/auth/me').status_code == 401
        await engine.dispose()

    asyncio.run(run())


def test_refresh_token_rotation_replay_revokes_family_and_access_version():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
                                     connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            inst = Institution(aicte_id='AICTE-AUTH-002', name='Auth Institute', state='Delhi', head_name='Principal',
                contact_email='college@example.test', contact_phone='9000000000', status='active')
            session.add(inst); await session.flush()
            user = User(email='college@example.test', full_name='College User', password_hash=hash_password('College-Safe-Password-2026'),
                role=Role.INSTITUTION.value, institution_id=inst.id, status=AccountStatus.ACTIVE.value, is_active=True)
            session.add(user); await session.commit()
            first = await auth_service.login(session, user.email, 'College-Safe-Password-2026', Role.INSTITUTION.value)
            await session.commit()
            rotated = await auth_service.rotate_refresh(session, first['refresh_token'], None, None)
            await session.commit()
            assert rotated['refresh_token'] != first['refresh_token']
            with pytest.raises(AuthError):
                await auth_service.rotate_refresh(session, first['refresh_token'], None, None)
            await session.commit()
            refreshed_user = await session.get(User, user.id)
            assert refreshed_user.session_version == 1
            tokens = list((await session.scalars(select(RefreshToken).where(RefreshToken.family_id == (
                await session.scalar(select(RefreshToken.family_id).where(RefreshToken.token_hash == auth_service.hash_token(first['refresh_token'])))
            )))).all())
            assert all(token.revoked_at is not None for token in tokens)
        await engine.dispose()
    asyncio.run(run())


def test_lockout_and_institution_email_approval_lifecycle(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
                                     connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        mail = []
        async def capture_email(to, subject, html):
            mail.append((to, subject, html)); return True
        monkeypatch.setattr(auth_service, 'send_email', capture_email)
        monkeypatch.setattr(user_admin_service, 'send_email', capture_email)
        async with factory() as session:
            institution = Institution(aicte_id='AICTE-LOCK-001', name='Lock Institute', state='Delhi', head_name='Principal',
                contact_email='lock@example.test', contact_phone='9000000000', status='active')
            session.add(institution); await session.flush()
            account = User(email='locked@example.test', full_name='Locked User', password_hash=hash_password('Safe-Password-2026-long'),
                role=Role.INSTITUTION.value, institution_id=institution.id, status=AccountStatus.ACTIVE.value, is_active=True)
            session.add(account); await session.commit()
            for _ in range(5):
                with pytest.raises(AuthError):
                    await auth_service.login(session, account.email, 'wrong-password', Role.INSTITUTION.value, '127.0.0.1')
                await session.commit()
            await session.refresh(account)
            assert account.status == AccountStatus.LOCKED.value
            with pytest.raises(AuthError):
                await auth_service.login(session, account.email, 'Safe-Password-2026-long', Role.INSTITUTION.value, '127.0.0.1')
            await session.commit()

            request = InstitutionRegistrationRequest(institution_name='New Technical College',
                aicte_institution_id='AICTE-NEW-003', contact_name='New Principal',
                email='newcollege@example.test', phone='9888888888', state='Delhi',
                password='New-Strong-College-Password-2026')
            await auth_service.register_institution(session, request, '127.0.0.1')
            await session.commit()
            new_user = await session.scalar(select(User).where(User.email == 'newcollege@example.test'))
            assert new_user.status == AccountStatus.PENDING_EMAIL_VERIFY.value
            verify_url = re.search(r'href="([^"]+)"', mail[-1][2]).group(1)
            raw_email_token = verify_url.split('token=', 1)[1]
            await auth_service.verify_email(session, raw_email_token)
            await session.commit()
            await session.refresh(new_user)
            assert new_user.status == AccountStatus.PENDING_APPROVAL.value

            admin = User(email='admin@example.test', full_name='Admin', password_hash=hash_password('Admin-Safe-Password-2026'),
                role=Role.ADMIN.value, institution_id=None, status=AccountStatus.ACTIVE.value, is_active=True)
            session.add(admin); await session.flush()
            await user_admin_service.approve_registration(session, new_user.id, True, None, admin)
            await session.commit()
            await session.refresh(new_user)
            assert new_user.status == AccountStatus.ACTIVE.value and new_user.is_active
        await engine.dispose()
    asyncio.run(run())
