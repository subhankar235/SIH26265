"""Manual portal authentication, rotating sessions and account lifecycle."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import AccountStatus, Role
from app.core.exceptions import AccountStatusError, AuthError, RateLimitError
from app.core.security import (create_access_token, decode_token, dummy_password_verify,
                               hash_password, hash_token, needs_rehash, verify_password,
                               encrypt_mfa_secret, decrypt_mfa_secret,
                               generate_totp_secret, verify_totp)
from app.models.auth_records import LoginAttempt, OneTimeToken, RefreshToken
from app.models.institution import Institution
from app.models.user import User
from app.schemas.auth import InstitutionRegistrationRequest, OfficialRegistrationRequest
from app.services.audit_service import record
from app.integrations.email_client import send_email

GENERIC_INVALID = 'Invalid email or password.'


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def user_public(user: User) -> dict:
    return {'id': user.id, 'email': user.email, 'full_name': user.full_name,
            'role': user.role, 'institution_id': user.institution_id,
            'must_change_password': user.must_change_password}


def validate_password_strength(password: str, email: str = '', full_name: str = '') -> None:
    if len(password) < 12:
        raise ValueError('Password must be at least 12 characters long.')
    lowered = password.casefold()
    common = {'password1234', 'qwerty123456', 'letmein123456', 'demoPass123!'.casefold()}
    if lowered in common:
        raise ValueError('Choose a less common password.')
    local = email.split('@', 1)[0].casefold() if email else ''
    if local and local in lowered:
        raise ValueError('Password must not contain your email name.')
    if full_name and len(full_name.strip()) >= 3 and full_name.casefold() in lowered:
        raise ValueError('Password must not contain your name.')


async def _log_attempt(session: AsyncSession, email: str, portal: str, success: bool,
                       reason: str | None, ip: str | None, user_agent: str | None) -> None:
    session.add(LoginAttempt(email_attempted=email, portal=portal, success=success,
                             failure_reason=reason, ip_address=ip, user_agent=(user_agent or '')[:500],
                             created_at=utcnow()))


async def _check_rate(session: AsyncSession, email: str, ip: str | None) -> None:
    since = utcnow() - timedelta(minutes=10)
    email_count = await session.scalar(select(func.count(LoginAttempt.id)).where(
        LoginAttempt.email_attempted == email, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since))
    ip_count = await session.scalar(select(func.count(LoginAttempt.id)).where(
        LoginAttempt.ip_address == ip, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since))
    if (email_count or 0) >= 10 or (ip_count or 0) >= 20:
        raise RateLimitError('Too many attempts. Try again later.')


async def throttle_public_action(session: AsyncSession, portal: str, email: str,
                                 ip: str | None, limit: int, minutes: int) -> None:
    since = utcnow() - timedelta(minutes=minutes)
    count = await session.scalar(select(func.count(LoginAttempt.id)).where(
        LoginAttempt.portal == portal, LoginAttempt.ip_address == ip,
        LoginAttempt.created_at >= since))
    if (count or 0) >= limit:
        raise RateLimitError('Too many attempts. Try again later.')
    await _log_attempt(session, email.lower(), portal, False, 'PUBLIC_ACTION', ip, None)


async def login(session: AsyncSession, email: str, password: str, portal: str,
                ip: str | None = None, user_agent: str | None = None) -> dict:
    normalized = email.strip().lower()
    await _check_rate(session, normalized, ip)
    user = await session.scalar(select(User).where(func.lower(User.email) == normalized))
    good_password = verify_password(password, user.password_hash) if user and user.password_hash else False
    if not user:
        dummy_password_verify(password)
    now = utcnow()
    if user and user.status == AccountStatus.LOCKED.value and user.locked_until and _aware(user.locked_until) <= now:
        user.status = AccountStatus.ACTIVE.value
        user.is_active = True
        user.locked_until = None
        user.failed_login_count = 0
    valid_roles = {role.value for role in Role}
    portal_roles = {'institution':Role.INSTITUTION.value,'official':Role.AICTE_OFFICIAL.value,
        'admin':Role.ADMIN.value,**{role.value:role.value for role in Role}}
    # Portal is a requested authentication context only; the database role remains
    # authoritative and must match it before any session is issued.
    requested_portal=getattr(portal,'value',portal)
    expected_role=portal_roles.get(requested_portal)
    audit_portal = requested_portal if requested_portal in portal_roles else 'invalid_portal'
    failure_reason = None
    if not user or not good_password:
        failure_reason = 'INVALID_CREDENTIALS'
    elif expected_role is None or user.role != expected_role:
        failure_reason = 'WRONG_PORTAL'
    elif user.status != AccountStatus.ACTIVE.value or not user.is_active:
        failure_reason = 'INACTIVE_ACCOUNT'
    elif user.role == Role.INSTITUTION.value and await session.scalar(select(Institution.status).where(Institution.id == user.institution_id)) != 'active':
        failure_reason = 'INACTIVE_ACCOUNT'
    elif user.locked_until and _aware(user.locked_until) > now:
        failure_reason = 'ACCOUNT_LOCKED'

    # Explain a blocked state only after both the password and requested portal role
    # match. Invalid credentials and wrong-portal attempts remain indistinguishable.
    if user and good_password and user.role == expected_role:
        status_messages = {
            AccountStatus.PENDING_EMAIL_VERIFY.value: 'Your registration is awaiting administrator approval.',
            AccountStatus.PENDING_APPROVAL.value: 'Your registration is awaiting administrator approval.',
            AccountStatus.REJECTED.value: 'This application was not approved. Contact a Super Admin for assistance.',
            AccountStatus.SUSPENDED.value: 'This account is temporarily suspended. Contact a Super Admin for assistance.',
            AccountStatus.DISABLED.value: 'This account is disabled. Contact a Super Admin for assistance.',
            AccountStatus.LOCKED.value: 'This account is temporarily locked. Try again later or contact a Super Admin.',
        }
        if user.status in status_messages or not user.is_active:
            await _log_attempt(session, normalized, audit_portal, False, user.status, ip, user_agent)
            await record(session, user.id, 'auth', user.id, 'LOGIN_BLOCKED_BY_ACCOUNT_STATUS', ip or '',
                         {'status': [None, user.status], 'role': [None, user.role]})
            raise AccountStatusError(status_messages.get(user.status, 'This account is inactive. Contact a Super Admin.'))

    if failure_reason:
        if user and failure_reason == 'INVALID_CREDENTIALS':
            user.failed_login_count += 1
            cfg = get_settings()
            if user.failed_login_count >= cfg.login_max_failures:
                user.status = AccountStatus.LOCKED.value
                user.locked_until = now + timedelta(minutes=cfg.lockout_minutes)
                await record(session, user.id, 'user', user.id, 'ACCOUNT_LOCKED', ip or '',
                             {'status': [AccountStatus.ACTIVE.value, AccountStatus.LOCKED.value]})
                await send_email(user.email, 'FDR-Shield account temporarily locked',
                    f'<p>Your account is temporarily locked after repeated failed sign-in attempts. Try again after {cfg.lockout_minutes} minutes or contact an administrator.</p>')
        await _log_attempt(session, normalized, audit_portal, False, failure_reason, ip, user_agent)
        await record(session, user.id if user else None, 'auth', user.id if user else 0,
            'LOGIN_FAILURE', ip or '', {'portal': [None, audit_portal], 'reason': [None, failure_reason]})
        raise AuthError(GENERIC_INVALID)

    assert user is not None
    if user.totp_secret or user.mfa_secret_enc:
        if user.password_hash and needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        await _log_attempt(session, normalized, audit_portal, False, 'MFA_REQUIRED', ip, user_agent)
        return {'mfa_required': True, 'mfa_token': create_access_token(str(user.id), user.role, 5,
                token_type='mfa', mfa_pending=True, portal=user.role)}
    return await _complete_login(session, user, user.role, ip, user_agent, password)


async def _complete_login(session: AsyncSession, user: User, portal: str,
                          ip: str | None, user_agent: str | None, password: str | None) -> dict:
    now = utcnow()
    if password is not None and user.password_hash and needs_rehash(user.password_hash):
        # Rehash legacy bcrypt/SHA-256 demo password format after a successful login.
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.status = AccountStatus.ACTIVE.value
    user.is_active = True
    user.last_login_at = now
    family = str(uuid.uuid4())
    raw_refresh = secrets.token_urlsafe(48)
    cfg = get_settings()
    session.add(RefreshToken(user_id=user.id, token_hash=hash_token(raw_refresh), family_id=family,
        issued_at=now, expires_at=now + timedelta(days=cfg.refresh_token_days),
        ip_address=ip, user_agent=(user_agent or '')[:500]))
    await _log_attempt(session, user.email.lower(), portal, True, None, ip, user_agent)
    await record(session, user.id, 'user', user.id, 'LOGIN_SUCCESS', ip or '', {'portal': [None, portal]})
    access = create_access_token(str(user.id), user.role, institution_id=user.institution_id,
                                 ver=user.session_version, sid=family)
    return {'access_token': access, 'refresh_token': raw_refresh, 'user': user_public(user),
            'mfa_required': False}


async def verify_mfa(session: AsyncSession, mfa_token: str, code: str, portal: str,
                     ip: str | None = None, user_agent: str | None = None) -> dict:
    try:
        claims = decode_token(mfa_token)
        if claims.get('typ') != 'mfa' or not claims.get('mfa_pending') or claims.get('portal') != portal:
            raise ValueError('MFA token is invalid for this portal')
        user = await session.get(User, int(claims['sub']))
    except Exception as exc:
        raise AuthError(GENERIC_INVALID) from exc
    if user:
        await _check_rate(session, user.email.lower(), ip)
    secret = None
    if user:
        stored_secret = user.mfa_secret_enc or user.totp_secret
        if stored_secret:
            try: secret = decrypt_mfa_secret(stored_secret)
            except ValueError: secret = None
    if not user or user.status != AccountStatus.ACTIVE.value or user.role != portal or not secret or not verify_totp(secret, code):
        await _log_attempt(session, user.email.lower() if user else '', portal, False, 'MFA_INVALID', ip, user_agent)
        await record(session, user.id if user else None, 'auth', user.id if user else 0,
            'MFA_FAILURE', ip or '', {'portal': [None, portal]})
        raise AuthError(GENERIC_INVALID)
    if user.totp_secret and not user.mfa_secret_enc:
        user.mfa_secret_enc = encrypt_mfa_secret(user.totp_secret)
        user.totp_secret = None
    return await _complete_login(session, user, portal, ip, user_agent, password=None)


async def rotate_refresh(session: AsyncSession, raw_token: str, ip: str | None, user_agent: str | None) -> dict:
    now = utcnow()
    digest = hash_token(raw_token)
    token = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest).with_for_update())
    if not token:
        raise AuthError('Session expired. Sign in again.')
    if token.used_at or token.revoked_at:
        await session.execute(update(RefreshToken).where(RefreshToken.user_id == token.user_id,
            RefreshToken.revoked_at.is_(None)).values(revoked_at=now))
        user = await session.get(User, token.user_id)
        if user: user.session_version += 1
        await record(session, token.user_id, 'refresh_family', token.user_id, 'TOKEN_REUSE_DETECTED', ip or '',
                     {'family_id': [None, token.family_id]})
        raise AuthError('Session expired. Sign in again.')
    user = await session.get(User, token.user_id)
    if not user or user.status != AccountStatus.ACTIVE.value or not user.is_active or _aware(token.expires_at) <= now:
        token.revoked_at = now
        raise AuthError('Session expired. Sign in again.')
    if user.role == Role.INSTITUTION.value and await session.scalar(select(Institution.status).where(Institution.id == user.institution_id)) != 'active':
        token.revoked_at = now
        raise AuthError('Session expired. Sign in again.')
    token.used_at = now
    new_raw = secrets.token_urlsafe(48)
    cfg = get_settings()
    session.add(RefreshToken(user_id=user.id, token_hash=hash_token(new_raw), family_id=token.family_id,
        issued_at=now, expires_at=now + timedelta(days=cfg.refresh_token_days), ip_address=ip,
        user_agent=(user_agent or '')[:500]))
    return {'access_token': create_access_token(str(user.id), user.role, institution_id=user.institution_id,
            ver=user.session_version, sid=token.family_id),
            'refresh_token': new_raw, 'user': user_public(user)}


async def logout(session: AsyncSession, refresh_raw: str | None, access_raw: str | None, ip: str | None) -> None:
    user = None
    family_id = None
    if refresh_raw:
        token = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_raw)))
        if token:
            user = await session.get(User, token.user_id)
            family_id = token.family_id
            await session.execute(update(RefreshToken).where(RefreshToken.family_id == token.family_id,
                RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    if not user and access_raw:
        try:
            claims = decode_token(access_raw)
            if claims.get('typ') == 'access':
                user = await session.get(User, int(claims['sub']))
                family_id = claims.get('sid')
                if family_id:
                    await session.execute(update(RefreshToken).where(RefreshToken.family_id == family_id,
                        RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
        except Exception:
            user = None
    if user:
        if not family_id:
            user.session_version += 1
        await record(session, user.id, 'user', user.id, 'LOGOUT', ip or '', {})


async def change_password(session: AsyncSession, user: User, current: str, new: str, ip: str | None) -> None:
    if not user.password_hash or not verify_password(current, user.password_hash):
        raise AuthError('Current password is incorrect.')
    validate_password_strength(new, user.email, user.full_name)
    if verify_password(new, user.password_hash):
        raise ValueError('Choose a password different from the current password.')
    user.password_hash = hash_password(new)
    user.session_version += 1
    user.must_change_password = False
    await session.execute(update(RefreshToken).where(RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    await record(session, user.id, 'user', user.id, 'PASSWORD_CHANGED', ip or '', {})
    await send_email(user.email, 'FDR-Shield password changed', '<p>Your account password was changed. If this was not you, contact an administrator.</p>')


async def issue_one_time_token(session: AsyncSession, user: User, purpose: str, ttl: timedelta) -> str:
    raw = secrets.token_urlsafe(36)
    now = utcnow()
    session.add(OneTimeToken(user_id=user.id, purpose=purpose, token_hash=hash_token(raw),
        expires_at=now + ttl, created_at=now))
    await session.flush()
    return raw


async def _consume_token(session: AsyncSession, raw: str, purpose: str) -> tuple[OneTimeToken, User]:
    item = await session.scalar(select(OneTimeToken).where(OneTimeToken.token_hash == hash_token(raw),
        OneTimeToken.purpose == purpose).with_for_update())
    if not item or item.used_at or _aware(item.expires_at) <= utcnow():
        raise AuthError('This link is invalid or expired.')
    item.used_at = utcnow()
    return item, await session.get(User, item.user_id)


async def register_institution(session: AsyncSession, data: InstitutionRegistrationRequest, ip: str | None) -> None:
    email = str(data.email).lower()
    if await session.scalar(select(User.id).where(func.lower(User.email) == email)):
        return  # Enumeration-resistant generic response; no existing account mutation.
    if await session.scalar(select(Institution.id).where(Institution.aicte_id == data.aicte_institution_id)):
        return
    validate_password_strength(data.password, email, data.contact_name)
    now = utcnow()
    institution = Institution(aicte_id=data.aicte_institution_id, name=data.institution_name,
        state=data.state, head_name=data.contact_name, contact_email=email, contact_phone=data.phone,
        address=data.address, status='pending_approval', created_at=now, updated_at=now)
    session.add(institution)
    await session.flush()
    user = User(email=email, full_name=data.contact_name, password_hash=hash_password(data.password),
        role=Role.INSTITUTION.value, institution_id=institution.id,
        status=AccountStatus.PENDING_APPROVAL.value, is_active=False)
    session.add(user)
    await session.flush()
    await record(session, user.id, 'user', user.id, 'USER_REGISTERED', ip or '', {'status': [None, user.status]})


async def register_official(session: AsyncSession, data: OfficialRegistrationRequest, ip: str | None) -> None:
    """Public AICTE Official application. It cannot create an active account."""
    email = str(data.email).lower()
    if await session.scalar(select(User.id).where(func.lower(User.email) == email)):
        return
    validate_password_strength(data.password, email, data.full_name)
    now = utcnow()
    user = User(email=email, full_name=data.full_name, password_hash=hash_password(data.password),
        role=Role.AICTE_OFFICIAL.value, institution_id=None,
        status=AccountStatus.PENDING_APPROVAL.value, is_active=False,
        created_at=now, updated_at=now)
    session.add(user)
    await session.flush()
    await record(session, user.id, 'user', user.id, 'OFFICIAL_APPLICATION_SUBMITTED', ip or '',
        {'role': [None, Role.AICTE_OFFICIAL.value], 'status': [None, user.status]})


async def verify_email(session: AsyncSession, raw: str) -> None:
    _, user = await _consume_token(session, raw, 'VERIFY_EMAIL')
    if not user: raise AuthError('This link is invalid or expired.')
    if user.status == AccountStatus.PENDING_EMAIL_VERIFY.value:
        user.email_verified_at = utcnow()
        user.status = AccountStatus.PENDING_APPROVAL.value
        await record(session, user.id, 'user', user.id, 'EMAIL_VERIFIED', 'system', {'status': [AccountStatus.PENDING_EMAIL_VERIFY.value, user.status]})


async def accept_invite(session: AsyncSession, raw: str, password: str, full_name: str | None) -> None:
    item, user = await _consume_token(session, raw, 'INVITE')
    if not user: raise AuthError('This link is invalid or expired.')
    validate_password_strength(password, user.email, full_name or user.full_name)
    user.password_hash = hash_password(password)
    user.session_version += 1
    user.full_name = full_name or user.full_name
    user.status = AccountStatus.ACTIVE.value
    user.is_active = True
    user.email_verified_at = utcnow()
    await record(session, user.id, 'user', user.id, 'INVITE_ACCEPTED', 'system', {'status': [AccountStatus.INVITED.value, user.status]})
    await send_email(user.email, 'FDR-Shield account activated', '<p>Your invited account is active and ready to use.</p>')


async def request_password_reset(session: AsyncSession, email: str) -> None:
    normalized = email.lower()
    user = await session.scalar(select(User).where(func.lower(User.email) == normalized))
    eligible = bool(user and user.status in {AccountStatus.ACTIVE.value, AccountStatus.LOCKED.value})
    raw = await issue_one_time_token(session, user, 'RESET_PASSWORD', timedelta(minutes=30)) if eligible and user else secrets.token_urlsafe(36)
    cfg = get_settings()
    await send_email(normalized, 'Reset your FDR-Shield password',
        f'<p>If a reset was requested for an eligible account, use this one-time link: <a href="{cfg.frontend_origin}/reset-password?token={raw}">Continue</a>.</p>')
    if eligible and user:
        await record(session, user.id, 'user', user.id, 'PASSWORD_RESET_REQUESTED', 'system', {})


async def reset_password(session: AsyncSession, raw: str, password: str) -> None:
    _, user = await _consume_token(session, raw, 'RESET_PASSWORD')
    if not user: raise AuthError('This link is invalid or expired.')
    if user.status not in {AccountStatus.ACTIVE.value, AccountStatus.LOCKED.value} or not user.is_active:
        raise AuthError('This link is invalid or expired.')
    validate_password_strength(password, user.email, user.full_name)
    user.password_hash = hash_password(password)
    user.status = AccountStatus.ACTIVE.value
    user.is_active = True
    user.failed_login_count = 0
    user.locked_until = None
    user.must_change_password = False
    user.session_version += 1
    await session.execute(update(RefreshToken).where(RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    await record(session, user.id, 'user', user.id, 'PASSWORD_RESET_COMPLETED', 'system', {})
    await send_email(user.email, 'FDR-Shield password reset completed', '<p>Your account password was reset. If this was not you, contact an administrator.</p>')


async def setup_mfa(session: AsyncSession, user: User) -> dict:
    secret = generate_totp_secret()
    user.mfa_secret_enc = encrypt_mfa_secret(secret)
    user.totp_secret = None
    await record(session, user.id, 'user', user.id, 'MFA_ENABLED', 'unknown', {'totp_enabled': [False, True]})
    import pyotp
    return {'secret': secret, 'otpauth_url': pyotp.TOTP(secret).provisioning_uri(user.email, issuer_name='FDR-Shield')}
