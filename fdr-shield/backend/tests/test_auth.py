from app.core.security import hash_password,verify_password,create_access_token,decode_token,generate_totp_secret,verify_totp
import pyotp

def test_password_jwt_and_totp_roundtrip():
    hashed=hash_password('safe-password')
    assert verify_password('safe-password',hashed) and not verify_password('bad',hashed)
    token=create_access_token('12','admin');assert decode_token(token)['sub']=='12'
    secret=generate_totp_secret();assert verify_totp(secret,pyotp.TOTP(secret).now())
