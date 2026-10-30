from app.core.security import hash_password,verify_password,create_access_token,decode_token,generate_totp_secret,verify_totp
from app.core.config import get_settings
from app.core.exceptions import AuthError
from jose import jwt
import pyotp
import pytest
from pydantic import ValidationError
from app.core.config import Settings

def test_password_jwt_and_totp_roundtrip():
    hashed=hash_password('safe-password')
    assert verify_password('safe-password',hashed) and not verify_password('bad',hashed)
    token=create_access_token('12','admin');assert decode_token(token)['sub']=='12'
    secret=generate_totp_secret();assert verify_totp(secret,pyotp.TOTP(secret).now())


def test_jwt_type_required_claims_and_reserved_claims_are_enforced():
    settings=get_settings()
    token=create_access_token('12','admin')
    claims=decode_token(token)
    assert {'sub','role','typ','jti','iat','exp'} <= claims.keys()
    with pytest.raises(ValueError):
        create_access_token('12','admin',typ='refresh')
    claims['typ']='refresh'
    forged=jwt.encode(claims,settings.jwt_secret,algorithm=settings.jwt_algorithm)
    with pytest.raises(AuthError):
        decode_token(forged)
    claims.pop('jti')
    malformed=jwt.encode(claims,settings.jwt_secret,algorithm=settings.jwt_algorithm)
    with pytest.raises(AuthError):
        decode_token(malformed)


def test_auth_settings_require_a_real_secret_and_secure_production_cookie_policy():
    with pytest.raises(ValidationError):
        Settings(_env_file=None,jwt_secret='too-short')
    with pytest.raises(ValidationError):
        Settings(_env_file=None,jwt_secret='replace-with-a-real-random-secret-123456789',
            app_env='prod',cookie_secure=False)
    settings=Settings(_env_file=None,jwt_secret='a-random-test-secret-with-more-than-32-bytes',
        app_env='prod',cookie_secure=True,frontend_origin='https://portal.example.test',
        cors_origins='https://portal.example.test',mfa_encryption_key='QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=')
    assert settings.access_token_minutes==720
    assert settings.refresh_token_days==30
