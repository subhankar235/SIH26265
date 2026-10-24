"""Authentication and MFA operations."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthError
from app.core.security import create_access_token, decode_token, generate_totp_secret, verify_password, verify_totp
from app.models.user import User
from app.services.audit_service import record


async def login(session: AsyncSession, email: str, password: str) -> dict:
    user = await session.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError('Invalid email or password')
    if user.totp_secret:
        return {'mfa_required': True, 'temp_token': create_access_token(str(user.id), user.role, 5, mfa_pending=True)}
    return {'access_token': create_access_token(str(user.id), user.role), 'mfa_required': False}


async def verify_mfa(session: AsyncSession, temp_token: str, code: str) -> dict:
    try:
        claims = decode_token(temp_token)
        if not claims.get('mfa_pending'): raise ValueError('MFA token required')
        user = await session.get(User, int(claims['sub']))
    except Exception as exc:
        raise AuthError('Invalid MFA session') from exc
    if not user or not user.is_active or not user.totp_secret or not verify_totp(user.totp_secret, code):
        raise AuthError('Invalid MFA code')
    return {'access_token': create_access_token(str(user.id), user.role), 'mfa_required': False}


async def setup_mfa(session: AsyncSession, user: User) -> dict:
    user.totp_secret = generate_totp_secret()
    await record(session, user.id, 'user', user.id, 'mfa_setup', 'unknown', {'totp_enabled': [False, True]})
    import pyotp
    return {'secret': user.totp_secret, 'otpauth_url': pyotp.TOTP(user.totp_secret).provisioning_uri(user.email, issuer_name='FDR-Shield')}
