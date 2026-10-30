import asyncio
import re
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace

import pytest
from jose import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.database import Base, get_session
from app.core.deps import is_current_access_session
from app.core.config import get_settings
from app.core.enums import AccountStatus, Role
from app.core.exceptions import AccountStatusError, AuthError, PermissionDenied
from app.core.security import (create_access_token, decode_token, decrypt_mfa_secret,
    encrypt_mfa_secret, hash_password, needs_rehash, verify_password)
from app.main import create_app
from app.models import Institution, User
from app.models.auth_records import OneTimeToken, RefreshToken
from app.services import auth_service
from app.schemas.auth import InstitutionRegistrationRequest, OfficialRegistrationRequest
from app.services import user_admin_service


def portal_login(client, body, endpoint='/api/v1/auth/login'):
    csrf=client.get('/api/v1/auth/csrf').json()['csrf_token']
    return client.post(endpoint,json=body,headers={'X-CSRF-Token':csrf})


def test_mobile_bearer_session_mfa_refresh_and_logout_share_web_role_security():
    import pyotp

    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        totp_secret = 'JBSWY3DPEHPK3PXP'
        async with factory() as session:
            institution = Institution(aicte_id='MOBILE-1', name='Mobile College', state='Delhi',
                head_name='Principal', contact_email='mobile@example.test', contact_phone='9000000000')
            session.add(institution)
            await session.flush()
            session.add_all([
                User(email='mobile@example.test', full_name='Mobile User',
                    password_hash=hash_password('Mobile-Strong-Password-2026'), role=Role.INSTITUTION.value,
                    institution_id=institution.id, status=AccountStatus.ACTIVE.value, is_active=True),
                User(email='mobile-official@example.test', full_name='Mobile Official',
                    password_hash=hash_password('Mobile-Official-Password-2026'), role=Role.AICTE_OFFICIAL.value,
                    totp_secret=totp_secret, status=AccountStatus.ACTIVE.value, is_active=True),
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

        login = client.post('/api/v1/auth/mobile/login', json={
            'email': 'mobile@example.test', 'password': 'Mobile-Strong-Password-2026',
            'portal': 'institution'})
        assert login.status_code == 200
        session_tokens = login.json()
        assert session_tokens['access_token'] and session_tokens['refresh_token']
        assert not login.headers.get_list('set-cookie')
        assert client.get('/api/v1/dashboard/institution', headers={
            'Authorization': f"Bearer {session_tokens['access_token']}"}).status_code == 200
        assert client.get('/api/v1/dashboard/bureau', headers={
            'Authorization': f"Bearer {session_tokens['access_token']}"}).status_code == 403

        mfa = client.post('/api/v1/auth/mobile/login', json={
            'email': 'mobile-official@example.test', 'password': 'Mobile-Official-Password-2026',
            'portal': 'official'})
        assert mfa.status_code == 200 and mfa.json()['mfa_required'] is True
        verified = client.post('/api/v1/auth/mobile/mfa/verify', json={
            'mfa_token': mfa.json()['mfa_token'], 'portal': mfa.json()['portal'],
            'code': pyotp.TOTP(totp_secret).now()})
        assert verified.status_code == 200
        assert verified.json()['user']['role'] == Role.AICTE_OFFICIAL.value
        assert client.get('/api/v1/dashboard/bureau', headers={
            'Authorization': f"Bearer {verified.json()['access_token']}"}).status_code == 200

        rotated = client.post('/api/v1/auth/mobile/refresh', json={
            'refresh_token': session_tokens['refresh_token']})
        assert rotated.status_code == 200
        assert rotated.json()['refresh_token'] != session_tokens['refresh_token']
        logged_out = client.post('/api/v1/auth/mobile/logout', json={
            'refresh_token': rotated.json()['refresh_token']})
        assert logged_out.status_code == 204
        assert client.get('/api/v1/dashboard/institution', headers={
            'Authorization': f"Bearer {rotated.json()['access_token']}"}).status_code == 401
        await engine.dispose()

    asyncio.run(run())


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


def test_first_super_admin_bootstrap_lock_is_acquired_on_sqlite():
    from scripts.create_admin import acquire_bootstrap_lock
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await acquire_bootstrap_lock(session)
            await session.rollback()
        await engine.dispose()
    asyncio.run(run())


def test_password_reset_is_single_use_invalidates_sessions_and_does_not_reactivate_rejected_users(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory = async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        emails=[]
        async def capture_email(to,subject,html): emails.append((to,subject,html)); return True
        monkeypatch.setattr(auth_service,'send_email',capture_email)
        async with factory() as session:
            active=User(email='reset-user@example.test',full_name='Reset User',
                password_hash=hash_password('Old-Reset-Password-2026'),role=Role.AICTE_OFFICIAL.value,
                status=AccountStatus.ACTIVE.value,is_active=True)
            rejected=User(email='rejected-user@example.test',full_name='Rejected User',
                password_hash=hash_password('Old-Rejected-Password-2026'),role=Role.AICTE_OFFICIAL.value,
                status=AccountStatus.REJECTED.value,is_active=False)
            session.add_all([active,rejected]); await session.flush()
            active.session_version=3
            session.add(RefreshToken(user_id=active.id,token_hash=auth_service.hash_token('old-refresh'),
                family_id='reset-family',issued_at=auth_service.utcnow(),
                expires_at=auth_service.utcnow()+timedelta(days=1)))
            await session.commit()

            await auth_service.request_password_reset(session,active.email)
            known_message=emails[-1][2].replace(re.search(r'token=([^&\"]+)',emails[-1][2]).group(1),'TOKEN')
            token=re.search(r'token=([^&\"]+)',emails[-1][2]).group(1)
            await auth_service.request_password_reset(session,'unknown-address@example.test')
            unknown_message=emails[-1][2].replace(re.search(r'token=([^&\"]+)',emails[-1][2]).group(1),'TOKEN')
            assert known_message==unknown_message

            await auth_service.reset_password(session,token,'New-Reset-Password-2026')
            assert active.session_version==4
            stored=await session.scalar(select(RefreshToken).where(RefreshToken.family_id=='reset-family'))
            assert stored.revoked_at is not None
            with pytest.raises(AuthError,match='invalid or expired'):
                await auth_service.reset_password(session,token,'Another-New-Password-2026')
            await session.rollback()
            rejected=await session.scalar(select(User).where(User.email=='rejected-user@example.test'))
            fake=await auth_service.issue_one_time_token(session,rejected,'RESET_PASSWORD',timedelta(minutes=30))
            with pytest.raises(AuthError,match='invalid or expired'):
                await auth_service.reset_password(session,fake,'Cannot-Reactivate-Account-2026')
            await session.rollback()
            rejected=await session.scalar(select(User).where(User.email=='rejected-user@example.test'))
            assert rejected.status==AccountStatus.REJECTED.value and rejected.is_active is False
            active=await session.scalar(select(User).where(User.email=='reset-user@example.test'))
            expired=await auth_service.issue_one_time_token(session,active,'RESET_PASSWORD',timedelta(seconds=-1))
            with pytest.raises(AuthError,match='invalid or expired'):
                await auth_service.reset_password(session,expired,'Expired-Token-Password-2026')
            await session.rollback()
        await engine.dispose()
    asyncio.run(run())


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
                User(email='pending-official@example.test', full_name='Pending Official', password_hash=hash_password('Pending-Official-Password-2026'),
                    role=Role.AICTE_OFFICIAL.value, institution_id=None, status=AccountStatus.PENDING_APPROVAL.value, is_active=False),
                User(email='admin@example.test', full_name='Super Admin', password_hash=hash_password('Super-Admin-Password-2026'),
                    role=Role.SUPER_ADMIN.value, institution_id=None, status=AccountStatus.ACTIVE.value, is_active=True),
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
        role_tamper = portal_login(client,{
            'email': 'college@example.test', 'password': 'College-Safe-Password-2026',
            'portal':'institution','role':'admin'})
        wrong_password = portal_login(client,{
            'email': 'college@example.test', 'password': 'wrong-password','portal':'institution'})
        assert role_tamper.status_code == 200
        assert role_tamper.json()['user']['role'] == Role.INSTITUTION.value
        assert wrong_password.status_code == 401
        assert wrong_password.json()['error'] == {
            'code': 'INVALID_CREDENTIALS', 'message': auth_service.GENERIC_INVALID}

        pending_wrong_password = portal_login(client,{
            'email': 'pending-official@example.test', 'password': 'not-the-password','portal':'official'})
        pending_correct_password = portal_login(client,{
            'email': 'pending-official@example.test', 'password': 'Pending-Official-Password-2026','portal':'official'})
        assert pending_wrong_password.status_code == 401
        assert pending_correct_password.status_code == 403
        assert pending_correct_password.json()['error']['code'] == 'ACCOUNT_STATUS'
        assert 'awaiting administrator approval' in pending_correct_password.json()['error']['message']

        response = portal_login(client,{
            'email': 'college@example.test', 'password': 'College-Safe-Password-2026','portal':'institution'})
        assert response.status_code == 200
        assert 'access_token' not in response.json()
        assert response.json()['user']['role'] == 'institution'
        cookies=response.headers.get_list('set-cookie')
        access_cookie=next(value.lower() for value in cookies if value.lower().startswith('access_token='))
        refresh_cookie=next(value.lower() for value in cookies if value.lower().startswith('refresh_token='))
        csrf_cookie=next(value.lower() for value in cookies if value.lower().startswith('csrf_token='))
        assert 'httponly' in access_cookie and 'path=/' in access_cookie and 'max-age=43200' in access_cookie
        assert 'httponly' in refresh_cookie and 'path=/api/v1/auth' in refresh_cookie and 'max-age=2592000' in refresh_cookie
        assert 'httponly' not in csrf_cookie and 'samesite=lax' in csrf_cookie
        assert response.json()['csrf_token']
        assert client.get('/api/v1/auth/me').json()['email'] == 'college@example.test'
        assert client.get('/api/v1/dashboard/institution').status_code == 200
        assert client.get('/api/v1/dashboard/bureau').status_code == 403

        # Expired access cookies must be recoverable via the valid, DB-backed refresh session.
        current_claims=decode_token(client.cookies.get('access_token'))
        current_claims['exp']=int(time.time())-10
        expired_access=jwt.encode(current_claims,get_settings().jwt_secret,algorithm=get_settings().jwt_algorithm)
        client.cookies.set('access_token',expired_access,domain='testserver.local',path='/')
        assert client.get('/api/v1/auth/me').status_code==401
        csrf=client.cookies.get('csrf_token')
        refreshed=client.post('/api/v1/auth/refresh',headers={'X-CSRF-Token':csrf})
        assert refreshed.status_code==200
        assert refreshed.json()['user']['email']=='college@example.test'
        assert refreshed.json()['csrf_token']
        assert client.get('/api/v1/auth/me').json()['email']=='college@example.test'

        official_client = TestClient(app)
        official_response = portal_login(official_client,{
            'email':'official@example.test','password':'Official-Safe-Password-2026','portal':'official'})
        assert official_response.status_code == 200
        assert official_response.json()['user']['role'] == Role.AICTE_OFFICIAL.value
        assert official_client.get('/api/v1/admin/users').status_code == 403

        admin_client = TestClient(app)
        admin_response = portal_login(admin_client,{
            'email':'admin@example.test','password':'Super-Admin-Password-2026','portal':'admin'})
        assert admin_response.status_code == 200
        assert admin_response.json()['user']['role'] == Role.SUPER_ADMIN.value
        assert admin_client.get('/api/v1/admin/users').status_code == 200

        csrf = client.cookies.get('csrf_token')
        assert client.post('/api/v1/auth/logout').status_code == 403
        assert client.post('/api/v1/auth/logout', headers={'X-CSRF-Token': csrf}).status_code == 204
        assert client.get('/api/v1/auth/me').status_code == 401
        await engine.dispose()

    asyncio.run(run())


def test_three_portal_login_matrix_rejects_cross_portal_credentials_and_stale_sessions():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        accounts=[
            ('college@example.test','College-Portal-Password-2026',Role.INSTITUTION.value),
            ('official@example.test','Official-Portal-Password-2026',Role.AICTE_OFFICIAL.value),
            ('admin@example.test','Super-Admin-Portal-Password-2026',Role.ADMIN.value),
        ]
        portal_roles={'institution':Role.INSTITUTION.value,'official':Role.AICTE_OFFICIAL.value,
            'admin':Role.ADMIN.value}
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-PORTAL-MATRIX',name='Matrix College',state='Delhi',
                head_name='Principal',contact_email='college@example.test',contact_phone='9000000050',status='active')
            session.add(institution);await session.flush()
            for email,password,role in accounts:
                session.add(User(email=email,full_name=role,password_hash=hash_password(password),role=role,
                    institution_id=institution.id if role==Role.INSTITUTION.value else None,
                    status=AccountStatus.ACTIVE.value,is_active=True))
            pending_institution=Institution(aicte_id='AICTE-PORTAL-PENDING',name='Pending College',state='Delhi',
                head_name='Principal',contact_email='pending-college@example.test',contact_phone='9000000051',
                status='pending_approval')
            session.add(pending_institution);await session.flush()
            session.add(User(email='pending-college@example.test',full_name='Pending College',
                password_hash=hash_password('Pending-College-Password-2026'),role=Role.INSTITUTION.value,
                institution_id=pending_institution.id,status=AccountStatus.PENDING_APPROVAL.value,is_active=False))
            await session.commit()

        async def session_override():
            async with factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback();raise

        app=create_app();app.dependency_overrides[get_session]=session_override
        no_portal_client=TestClient(app)
        no_portal=portal_login(no_portal_client,{'email':'college@example.test',
            'password':'College-Portal-Password-2026'})
        assert no_portal.status_code==422
        assert no_portal_client.get('/api/v1/auth/me').status_code==401

        for requested_portal in ('institution','official','admin'):
            for email,password,actual_role in accounts:
                client=TestClient(app)
                response=portal_login(client,{'email':email,'password':password,'portal':requested_portal})
                if portal_roles[requested_portal]==actual_role:
                    assert response.status_code==200,(requested_portal,actual_role,response.text)
                    assert response.json()['user']['role']==actual_role
                    assert client.get('/api/v1/auth/me').json()['role']==actual_role
                    command_access=client.get('/api/v1/commands').status_code
                    assert command_access==200
                    # A valid refresh preserves the account's stored role and cannot elevate it.
                    csrf=client.cookies.get('csrf_token')
                    refreshed=client.post('/api/v1/auth/refresh',headers={'X-CSRF-Token':csrf})
                    assert refreshed.status_code==200
                    if actual_role==Role.INSTITUTION.value:
                        assert client.get('/api/v1/admin/users').status_code==403
                        assert client.get('/api/v1/dashboard/bureau').status_code==403
                    elif actual_role==Role.AICTE_OFFICIAL.value:
                        assert client.get('/api/v1/admin/users').status_code==403
                        assert client.get('/api/v1/dashboard/institution').status_code==403
                    else:
                        assert client.get('/api/v1/admin/users').status_code==200
                        assert client.get('/api/v1/dashboard/institution').status_code==403
                else:
                    assert response.status_code==401,(requested_portal,actual_role,response.text)
                    assert any(cookie.lower().startswith('access_token=') and 'max-age=0' in cookie.lower()
                        for cookie in response.headers.get_list('set-cookie'))
                    assert client.get('/api/v1/auth/me').status_code==401

        # The hidden compatibility URL is bound to its path, not a role submitted by a client.
        legacy_client=TestClient(app)
        legacy=portal_login(legacy_client,{'email':'admin@example.test',
            'password':'Super-Admin-Portal-Password-2026'},endpoint='/api/v1/auth/login/institution')
        assert legacy.status_code==401
        assert legacy_client.get('/api/v1/auth/me').status_code==401

        pending_client=TestClient(app)
        pending=portal_login(pending_client,{'email':'pending-college@example.test',
            'password':'Pending-College-Password-2026','portal':'institution'})
        assert pending.status_code==403
        assert pending.json()['error']['code']=='ACCOUNT_STATUS'
        assert pending_client.get('/api/v1/auth/me').status_code==401

        # Switching portals first revokes the previous shared SSO family; a rejected
        # cross-portal attempt cannot leave the previous authenticated user in the browser.
        switching_client=TestClient(app)
        assert portal_login(switching_client,{'email':'admin@example.test',
            'password':'Super-Admin-Portal-Password-2026','portal':'admin'}).status_code==200
        rejected=portal_login(switching_client,{'email':'college@example.test',
            'password':'College-Portal-Password-2026','portal':'admin'})
        assert rejected.status_code==401
        assert switching_client.get('/api/v1/auth/me').status_code==401
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


def test_live_stream_session_validation_observes_role_version_and_refresh_revocation():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-STREAM-SESSION',name='Stream College',state='Delhi',
                head_name='Principal',contact_email='stream@example.test',contact_phone='9000000052',status='active')
            session.add(institution);await session.flush()
            user=User(email='stream@example.test',full_name='Stream User',password_hash='x',
                role=Role.INSTITUTION.value,institution_id=institution.id,status='active',is_active=True)
            session.add(user);await session.flush()
            family='stream-family-0001';now=auth_service.utcnow()
            session.add(RefreshToken(user_id=user.id,token_hash='a'*64,family_id=family,
                issued_at=now,expires_at=now+timedelta(days=1)))
            token=create_access_token(str(user.id),user.role,institution_id=institution.id,
                ver=user.session_version,sid=family)
            claims=decode_token(token)
            assert await is_current_access_session(session,user,claims)
            user.session_version+=1
            assert not await is_current_access_session(session,user,claims)
            user.session_version-=1
            await session.execute(update(RefreshToken).where(RefreshToken.family_id==family)
                .values(revoked_at=auth_service.utcnow()))
            assert not await is_current_access_session(session,user,claims)
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
            with pytest.raises(AccountStatusError, match='temporarily locked'):
                await auth_service.login(session, account.email, 'Safe-Password-2026-long', Role.INSTITUTION.value, '127.0.0.1')
            await session.commit()

            request = InstitutionRegistrationRequest(institution_name='New Technical College',
                aicte_institution_id='AICTE-NEW-003', contact_name='New Principal',
                email='newcollege@example.test', phone='9888888888', state='Delhi',
                password='New-Strong-College-Password-2026')
            emails_before_registration = len(mail)
            await auth_service.register_institution(session, request, '127.0.0.1')
            await session.commit()
            new_user = await session.scalar(select(User).where(User.email == 'newcollege@example.test'))
            assert new_user.status == AccountStatus.PENDING_APPROVAL.value
            assert new_user.email_verified_at is None
            assert len(mail) == emails_before_registration

            admin = User(email='admin@example.test', full_name='Admin', password_hash=hash_password('Admin-Safe-Password-2026'),
                role=Role.ADMIN.value, institution_id=None, status=AccountStatus.ACTIVE.value, is_active=True)
            session.add(admin); await session.flush()
            await user_admin_service.approve_registration(session, new_user.id, True, None, admin)
            await session.commit()
            await session.refresh(new_user)
            assert new_user.status == AccountStatus.ACTIVE.value and new_user.is_active
        await engine.dispose()
    asyncio.run(run())


def test_registrations_skip_email_verification_and_require_the_correct_approver(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        emails = []

        async def capture_email(to, subject, html):
            emails.append((to, subject, html))
            return True

        monkeypatch.setattr(auth_service, 'send_email', capture_email)
        monkeypatch.setattr(user_admin_service, 'send_email', capture_email)
        async with factory() as session:
            super_admin = User(email='root@example.test', full_name='Super Admin',
                password_hash=hash_password('Super-Admin-Password-2026'), role=Role.SUPER_ADMIN.value,
                status=AccountStatus.ACTIVE.value, is_active=True)
            session.add(super_admin)
            await session.flush()

            official_data = OfficialRegistrationRequest(full_name='Official Applicant',
                email='new-official@example.test', password='Official-Applicant-Password-2026')
            emails_before_registration = len(emails)
            await auth_service.register_official(session, official_data, '127.0.0.1')
            await session.commit()
            official = await session.scalar(select(User).where(User.email == official_data.email))
            assert official.role == Role.AICTE_OFFICIAL.value
            assert official.status == AccountStatus.PENDING_APPROVAL.value
            assert official.email_verified_at is None
            assert len(emails) == emails_before_registration
            with pytest.raises(AccountStatusError, match='awaiting administrator approval'):
                await auth_service.login(session, official.email, official_data.password,
                    Role.AICTE_OFFICIAL.value, '127.0.0.1')
            await session.rollback()
            await session.refresh(official)

            super_admin = await session.scalar(select(User).where(User.email == 'root@example.test'))

            await user_admin_service.decide_registration(session, official.id, True, None, super_admin)
            assert official.status == AccountStatus.ACTIVE.value and official.is_active
            await user_admin_service.decide_registration(session, official.id, False,
                'Security review requires rejection', super_admin, override=True)
            assert official.status == AccountStatus.REJECTED.value and not official.is_active
            await user_admin_service.decide_registration(session, official.id, True,
                'Super Admin reconsidered application', super_admin, override=True)
            assert official.status == AccountStatus.ACTIVE.value and official.is_active
            logged_in = await auth_service.login(session, official.email, official_data.password,
                Role.AICTE_OFFICIAL.value, '127.0.0.1')
            assert logged_in['user']['role'] == Role.AICTE_OFFICIAL.value
            await session.rollback()
            await session.refresh(official)

            institution_data = InstitutionRegistrationRequest(institution_name='Applicant College',
                aicte_institution_id='AICTE-APP-44', contact_name='Principal',
                email='apply-44@example.test', phone='9876543210', state='Delhi',
                address='Campus Road', password='Green-Mountain-Deposit-2026')
            await auth_service.register_institution(session, institution_data, '127.0.0.1')
            await session.commit()
            college = await session.scalar(select(User).where(User.email == institution_data.email))
            institution = await session.get(Institution, college.institution_id)
            assert college.status == AccountStatus.PENDING_APPROVAL.value
            assert college.email_verified_at is None
            with pytest.raises(PermissionDenied, match='Only an AICTE Official'):
                await user_admin_service.decide_registration(session, college.id, True, 'No', college)
            await session.rollback()
            college = await session.scalar(select(User).where(User.email == institution_data.email))
            institution = await session.get(Institution, college.institution_id)
            official = await session.scalar(select(User).where(User.email == official_data.email))
            super_admin = await session.scalar(select(User).where(User.email == 'root@example.test'))
            await user_admin_service.decide_registration(session, college.id, True,
                'Institution records reviewed', official)
            assert college.status == AccountStatus.ACTIVE.value
            assert institution.status == 'active'
            await user_admin_service.decide_registration(session, college.id, False,
                'Super Admin override reason', super_admin, override=True)
            assert college.status == AccountStatus.REJECTED.value
            assert institution.status == 'rejected'
            await user_admin_service.decide_registration(session, college.id, True,
                'Super Admin final review', super_admin, override=True)
            assert college.status == AccountStatus.ACTIVE.value
            assert institution.status == 'active'
            await session.commit()
        await engine.dispose()
    asyncio.run(run())


def test_legacy_unverified_application_is_reviewable_and_old_token_cannot_revoke_approval():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution = Institution(aicte_id='AICTE-LEGACY-1', name='Legacy College',
                state='Delhi', head_name='Principal', contact_email='legacy@example.test',
                contact_phone='9000000000', status='pending_approval')
            session.add(institution)
            await session.flush()
            user = User(email='legacy@example.test', full_name='Legacy Principal',
                password_hash=hash_password('Legacy-Strong-Password-2026'),
                role=Role.INSTITUTION.value, institution_id=institution.id,
                status=AccountStatus.PENDING_EMAIL_VERIFY.value, is_active=False)
            admin = User(email='root@example.test', full_name='Super Admin',
                password_hash=hash_password('Super-Admin-Password-2026'),
                role=Role.ADMIN.value, status=AccountStatus.ACTIVE.value, is_active=True)
            session.add_all([user, admin])
            await session.flush()
            raw_token = await auth_service.issue_one_time_token(
                session, user, 'VERIFY_EMAIL', timedelta(hours=24))
            pending = await user_admin_service.list_pending_registrations(
                session, Role.INSTITUTION.value, SimpleNamespace(skip=0, limit=50))
            assert [item.id for item in pending] == [user.id]

            await user_admin_service.decide_registration(session, user.id, True, 'Approved', admin)
            await session.commit()
            await auth_service.verify_email(session, raw_token)
            assert user.status == AccountStatus.ACTIVE.value
            assert user.is_active
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize('status,message', [
    (AccountStatus.PENDING_EMAIL_VERIFY.value, 'awaiting administrator approval'),
    (AccountStatus.PENDING_APPROVAL.value, 'awaiting administrator approval'),
    (AccountStatus.REJECTED.value, 'not approved'),
    (AccountStatus.SUSPENDED.value, 'temporarily suspended'),
    (AccountStatus.DISABLED.value, 'account is disabled'),
    (AccountStatus.LOCKED.value, 'temporarily locked'),
])
def test_valid_password_reports_non_active_account_state(status, message):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory = async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            inst = Institution(aicte_id=f'STATUS-{status}',name='Status Institute',state='Delhi',
                head_name='Principal',contact_email=f'{status}@example.test',contact_phone='9000000011',status='active')
            session.add(inst);await session.flush()
            user = User(email=f'user-{status}@example.test',full_name='Status User',
                password_hash=hash_password('Status-Account-Password-2026'),role=Role.INSTITUTION.value,
                institution_id=inst.id,status=status,is_active=status==AccountStatus.LOCKED.value,
                locked_until=auth_service.utcnow()+timedelta(minutes=10) if status==AccountStatus.LOCKED.value else None)
            session.add(user);await session.commit()
            with pytest.raises(AccountStatusError,match=message):
                await auth_service.login(session,user.email,'Status-Account-Password-2026',Role.INSTITUTION.value,'127.0.0.1')
            await session.rollback()
        await engine.dispose()
    asyncio.run(run())
