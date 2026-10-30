"""Consistent cookie policy for the shared role-derived browser session."""
from fastapi import Response

from app.core.config import get_settings
from app.core.security import make_csrf_token

COOKIE_ACCESS = 'access_token'
COOKIE_REFRESH = 'refresh_token'
COOKIE_CSRF = 'csrf_token'
COOKIE_MFA = 'mfa_token'


def _options() -> dict:
    settings=get_settings()
    return {'secure':settings.cookie_secure,'samesite':settings.cookie_samesite,
            'domain':settings.cookie_domain or None}


def set_csrf_cookie(response: Response) -> str:
    token=make_csrf_token()
    response.set_cookie(COOKIE_CSRF,token,httponly=False,path='/',max_age=7*24*3600,**_options())
    return token


def set_session_cookies(response: Response, data: dict) -> str:
    settings=get_settings();options=_options()
    response.set_cookie(COOKIE_ACCESS,data['access_token'],httponly=True,path='/',
        max_age=settings.access_token_minutes*60,**options)
    response.set_cookie(COOKIE_REFRESH,data['refresh_token'],httponly=True,path='/api/v1/auth',
        max_age=settings.refresh_token_days*86400,**options)
    response.delete_cookie(COOKIE_MFA,path='/api/v1/auth',httponly=True,**options)
    return set_csrf_cookie(response)


def set_mfa_cookie(response: Response, token: str) -> str:
    response.set_cookie(COOKIE_MFA,token,httponly=True,path='/api/v1/auth',max_age=300,**_options())
    return set_csrf_cookie(response)


def clear_session_cookies(response: Response) -> None:
    options=_options()
    response.delete_cookie(COOKIE_ACCESS,path='/',httponly=True,**options)
    response.delete_cookie(COOKIE_REFRESH,path='/api/v1/auth',httponly=True,**options)
    response.delete_cookie(COOKIE_MFA,path='/api/v1/auth',httponly=True,**options)
    response.delete_cookie(COOKIE_CSRF,path='/',httponly=False,**options)
