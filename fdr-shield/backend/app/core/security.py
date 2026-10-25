from datetime import datetime, timedelta, timezone
import hashlib, secrets, bcrypt
import hmac
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
import pyotp
from jose import jwt, JWTError
from app.core.config import get_settings
from app.core.exceptions import AuthError

_argon = PasswordHasher()
def _password_bytes(plain:str)->bytes:return hashlib.sha256(plain.encode('utf-8')).digest()
_LEGACY_DUMMY = bcrypt.hashpw(_password_bytes('dummy-password-not-used'), bcrypt.gensalt(rounds=12))
def hash_password(plain: str) -> str: return _argon.hash(plain)
def verify_password(plain: str, hashed: str) -> bool:
    try:
        if hashed.startswith('$argon2'):
            return _argon.verify(hashed, plain)
        # Existing demo accounts used bcrypt over a SHA-256 prehash; verify during migration.
        return bcrypt.checkpw(_password_bytes(plain),hashed.encode('ascii'))
    except Exception: return False
def needs_rehash(hashed: str) -> bool:
    if not hashed.startswith('$argon2'):
        return True
    try: return _argon.check_needs_rehash(hashed)
    except (InvalidHashError, VerifyMismatchError): return True

def dummy_password_verify(plain: str) -> None:
    # Keep the unknown-user path computationally similar to legacy bcrypt accounts.
    bcrypt.checkpw(_password_bytes(plain), _LEGACY_DUMMY)

def hash_token(token: str) -> str: return hashlib.sha256(token.encode('utf-8')).hexdigest()

def make_csrf_token() -> str:
    nonce = secrets.token_urlsafe(24)
    signature = hmac.new(get_settings().jwt_secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    return f'{nonce}.{signature}'

def verify_csrf_token(token: str) -> bool:
    try:
        nonce, signature = token.rsplit('.', 1)
        expected = hmac.new(get_settings().jwt_secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (ValueError, AttributeError):
        return False

def encrypt_mfa_secret(secret: str) -> str:
    key = get_settings().mfa_encryption_key
    if not key:
        if get_settings().app_env not in {'dev', 'development', 'test'}:
            raise RuntimeError('MFA_ENCRYPTION_KEY is required to protect TOTP secrets.')
        key = __import__('base64').urlsafe_b64encode(hashlib.sha256(get_settings().jwt_secret.encode()).digest()).decode()
    return Fernet(key.encode()).encrypt(secret.encode()).decode()

def decrypt_mfa_secret(value: str) -> str:
    if not value.startswith('gAAAA'):
        return value  # legacy plaintext TOTP secret; callers re-encrypt after successful verification
    key = get_settings().mfa_encryption_key
    if not key:
        key = __import__('base64').urlsafe_b64encode(hashlib.sha256(get_settings().jwt_secret.encode()).digest()).decode()
    try: return Fernet(key.encode()).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc: raise ValueError('Stored MFA secret cannot be decrypted.') from exc

def create_access_token(subject: str, role: str, expires_minutes: int | None = None, **claims) -> str:
    s=get_settings(); token_type=claims.pop('token_type','access'); payload={'sub':subject,'role':role,'typ':token_type,'jti':secrets.token_urlsafe(16),'iat':datetime.now(timezone.utc),'exp':datetime.now(timezone.utc)+timedelta(minutes=expires_minutes or s.access_token_minutes),**claims}
    return jwt.encode(payload,s.jwt_secret,algorithm=s.jwt_algorithm)
def decode_token(token: str) -> dict:
    s=get_settings()
    try: return jwt.decode(token,s.jwt_secret,algorithms=[s.jwt_algorithm])
    except JWTError as exc: raise AuthError('Invalid or expired token') from exc
def generate_totp_secret() -> str: return pyotp.random_base32()
def verify_totp(secret: str, code: str) -> bool: return pyotp.TOTP(secret).verify(code, valid_window=1)
