from datetime import datetime, timedelta, timezone
import hmac,hashlib,bcrypt
import pyotp
from jose import jwt, JWTError
from app.core.config import get_settings
from app.core.exceptions import AuthError

def _password_bytes(plain:str)->bytes:return hashlib.sha256(plain.encode('utf-8')).digest()
def hash_password(plain: str) -> str: return bcrypt.hashpw(_password_bytes(plain),bcrypt.gensalt()).decode('ascii')
def verify_password(plain: str, hashed: str) -> bool:
    try: return bcrypt.checkpw(_password_bytes(plain),hashed.encode('ascii'))
    except Exception: return False
def create_access_token(subject: str, role: str, expires_minutes: int | None = None, **claims) -> str:
    s=get_settings(); payload={'sub':subject,'role':role,'exp':datetime.now(timezone.utc)+timedelta(minutes=expires_minutes or s.access_token_minutes),**claims}
    return jwt.encode(payload,s.jwt_secret,algorithm=s.jwt_algorithm)
def decode_token(token: str) -> dict:
    s=get_settings()
    try: return jwt.decode(token,s.jwt_secret,algorithms=[s.jwt_algorithm])
    except JWTError as exc: raise AuthError('Invalid or expired token') from exc
def generate_totp_secret() -> str: return pyotp.random_base32()
def verify_totp(secret: str, code: str) -> bool: return pyotp.TOTP(secret).verify(code, valid_window=1)
