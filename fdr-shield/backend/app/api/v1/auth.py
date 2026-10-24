"""Manual three-portal authentication using short-lived HttpOnly cookies."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.database import get_session
from app.core.deps import get_current_user, get_client_ip
from app.core.enums import Role
from app.core.exceptions import AuthError, RateLimitError
from app.core.security import make_csrf_token
from app.schemas.auth import (LoginRequest, MfaVerifyRequest, PasswordChangeRequest,
    InstitutionRegistrationRequest, ForgotPasswordRequest, TokenBody, ResetPasswordRequest,
    InviteAcceptRequest)
from app.services import auth_service

router = APIRouter()
COOKIE_ACCESS = 'access_token'
COOKIE_REFRESH = 'refresh_token'
COOKIE_CSRF = 'csrf_token'


def _cookie_options() -> dict:
    cfg = get_settings()
    return {'secure': cfg.cookie_secure, 'samesite': cfg.cookie_samesite,
            'domain': cfg.cookie_domain or None}


def _set_csrf(response: Response) -> None:
    response.set_cookie(COOKIE_CSRF, make_csrf_token(), httponly=False, path='/',
        max_age=7 * 24 * 3600, **_cookie_options())


def _set_session(response: Response, data: dict) -> None:
    cfg = get_settings()
    options = _cookie_options()
    response.set_cookie(COOKIE_ACCESS, data['access_token'], httponly=True, path='/',
        max_age=cfg.access_token_minutes * 60, **options)
    response.set_cookie(COOKIE_REFRESH, data['refresh_token'], httponly=True,
        path='/api/v1/auth', max_age=cfg.refresh_token_days * 86400, **options)
    response.delete_cookie('mfa_token', path='/api/v1/auth', **options)
    _set_csrf(response)


def _clear_session(response: Response) -> None:
    options = _cookie_options()
    response.delete_cookie(COOKIE_ACCESS, path='/', **options)
    response.delete_cookie(COOKIE_REFRESH, path='/api/v1/auth', **options)
    response.delete_cookie('mfa_token', path='/api/v1/auth', **options)
    response.delete_cookie(COOKIE_CSRF, path='/', **options)


async def _portal_login(portal: str, body: LoginRequest, request: Request,
                        response: Response, session: AsyncSession) -> dict:
    try:
        data = await auth_service.login(session, str(body.email), body.password, portal,
            get_client_ip(request), request.headers.get('user-agent'))
    except RateLimitError:
        await session.commit()
        raise
    except AuthError:
        await session.commit()  # retain failed-attempt and lockout records
        raise AuthError(auth_service.GENERIC_INVALID)
    if data.get('mfa_required'):
        cfg = get_settings()
        response.set_cookie('mfa_token', data['mfa_token'], httponly=True, path='/api/v1/auth',
            max_age=300, **_cookie_options())
        _set_csrf(response)
        return {'mfa_required': True}
    _set_session(response, data)
    return {'mfa_required': False, 'user': data['user']}


@router.post('/login/institution')
async def institution_login(body: LoginRequest, request: Request, response: Response,
                            session: AsyncSession = Depends(get_session)):
    return await _portal_login(Role.INSTITUTION.value, body, request, response, session)


@router.post('/login/official')
async def official_login(body: LoginRequest, request: Request, response: Response,
                         session: AsyncSession = Depends(get_session)):
    return await _portal_login(Role.AICTE_OFFICIAL.value, body, request, response, session)


@router.post('/login/admin')
async def admin_login(body: LoginRequest, request: Request, response: Response,
                      session: AsyncSession = Depends(get_session)):
    return await _portal_login(Role.ADMIN.value, body, request, response, session)


@router.post('/mfa/verify')
async def verify_mfa(body: MfaVerifyRequest, request: Request, response: Response,
                     session: AsyncSession = Depends(get_session)):
    token = request.cookies.get('mfa_token')
    if not token: raise AuthError(auth_service.GENERIC_INVALID)
    try:
        claims = auth_service.decode_token(token)
        portal = claims.get('portal', '')
        data = await auth_service.verify_mfa(session, token, body.code, portal,
            get_client_ip(request), request.headers.get('user-agent'))
    except AuthError:
        await session.commit()
        raise
    _set_session(response, data)
    return {'user': data['user']}


@router.post('/refresh')
async def refresh(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    raw = request.cookies.get(COOKIE_REFRESH)
    if not raw: raise AuthError('Session expired. Sign in again.')
    try:
        data = await auth_service.rotate_refresh(session, raw, get_client_ip(request), request.headers.get('user-agent'))
    except AuthError as exc:
        await session.commit()
        failed = JSONResponse(status_code=401, content={'error': {'code': 'INVALID_CREDENTIALS', 'message': str(exc)}})
        _clear_session(failed)
        return failed
    _set_session(response, data)
    return {'user': data['user']}


@router.post('/logout', status_code=204)
async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    await auth_service.logout(session, request.cookies.get(COOKIE_REFRESH), request.cookies.get(COOKIE_ACCESS), get_client_ip(request))
    _clear_session(response)
    response.status_code = 204
    return response


@router.get('/me')
async def me(user=Depends(get_current_user)):
    return auth_service.user_public(user)


@router.post('/change-password', status_code=204)
async def change_password(body: PasswordChangeRequest, request: Request, response: Response,
                          session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    try:
        auth_service.validate_password_strength(body.new_password, user.email, user.full_name)
        await auth_service.change_password(session, user, body.current_password, body.new_password, get_client_ip(request))
        _clear_session(response)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/forgot-password', status_code=202)
async def forgot_password(body: ForgotPasswordRequest, request: Request, session: AsyncSession = Depends(get_session)):
    await auth_service.throttle_public_action(session, 'forgot_password', str(body.email), get_client_ip(request), 5, 60)
    await auth_service.request_password_reset(session, str(body.email))
    return {'message': 'If the account is eligible, a reset link will be sent.'}


@router.post('/reset-password', status_code=204)
async def reset_password(body: ResetPasswordRequest, session: AsyncSession = Depends(get_session)):
    try: await auth_service.reset_password(session, body.token, body.new_password)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post('/register/institution', status_code=202)
async def register_institution(body: InstitutionRegistrationRequest, request: Request,
                                session: AsyncSession = Depends(get_session)):
    await auth_service.throttle_public_action(session, 'register', str(body.email), get_client_ip(request), 5, 60)
    try: await auth_service.register_institution(session, body, get_client_ip(request))
    except IntegrityError:
        await session.rollback()
        await auth_service._send_registration_ack(str(body.email))
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    return {'message': 'If the registration can be processed, an email verification link will be sent.'}


@router.post('/verify-email', status_code=204)
async def verify_email(body: TokenBody, session: AsyncSession = Depends(get_session)):
    await auth_service.verify_email(session, body.token)


@router.post('/accept-invite', status_code=204)
async def accept_invite(body: InviteAcceptRequest, session: AsyncSession = Depends(get_session)):
    try: await auth_service.accept_invite(session, body.token, body.password, body.full_name)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post('/mfa/setup')
async def setup_mfa(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return await auth_service.setup_mfa(session, user)
