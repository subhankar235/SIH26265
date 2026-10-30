"""Manual three-portal authentication using HttpOnly cookies and DB-backed refresh rotation."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.database import get_session
from app.core.deps import get_current_user, get_client_ip
from app.core.exceptions import AccountStatusError, AuthError, RateLimitError
from app.core.cookies import (COOKIE_ACCESS, COOKIE_CSRF, COOKIE_REFRESH,
    clear_session_cookies, set_csrf_cookie, set_mfa_cookie, set_session_cookies)
from app.schemas.auth import (LoginRequest, LoginCredentials, MfaVerifyRequest, PasswordChangeRequest,
    InstitutionRegistrationRequest, ForgotPasswordRequest, TokenBody, ResetPasswordRequest,
    InviteAcceptRequest, OfficialRegistrationRequest, MobileMfaVerifyRequest,
    MobileRefreshRequest, MobileLogoutRequest)
from app.schemas.super_admin_setup import SuperAdminSetupRequest
from app.services import auth_service

router = APIRouter()
logger=logging.getLogger(__name__)


def _login_error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    payload={'code':code,'message':message}
    request_id=getattr(request.state,'request_id',None)
    if request_id: payload['request_id']=request_id
    response=JSONResponse(status_code=status,content={'error':payload})
    clear_session_cookies(response)
    return response


async def _shared_login(body: LoginCredentials, request: Request,
                        response: Response, session: AsyncSession, portal: str) -> dict | JSONResponse:
    # A portal login replaces the current shared SSO session. Middleware requires
    # CSRF on login requests so a cross-site request cannot revoke that session.
    await auth_service.logout(session,request.cookies.get(COOKIE_REFRESH),
        request.cookies.get(COOKIE_ACCESS),get_client_ip(request))
    try:
        data = await auth_service.login(session, str(body.email), body.password, portal,
            get_client_ip(request), request.headers.get('user-agent'))
    except RateLimitError as exc:
        await session.commit()
        return _login_error_response(request,429,'RATE_LIMITED',str(exc))
    except AccountStatusError as exc:
        await session.commit()
        return _login_error_response(request,403,'ACCOUNT_STATUS',str(exc))
    except AuthError:
        await session.commit()  # retain failed-attempt and lockout records
        logger.info('auth_login_rejected',extra={'request_id':getattr(request.state,'request_id',None),
            'portal':portal,'failure_category':'invalid_credentials_or_wrong_portal'})
        return _login_error_response(request,401,'INVALID_CREDENTIALS',auth_service.GENERIC_INVALID)
    if data.get('mfa_required'):
        logger.info('auth_mfa_required',extra={'request_id':getattr(request.state,'request_id',None),
            'portal':portal})
        csrf=set_mfa_cookie(response,data['mfa_token'])
        return {'mfa_required': True,'csrf_token':csrf}
    csrf=set_session_cookies(response, data)
    logger.info('auth_login_succeeded',extra={'request_id':getattr(request.state,'request_id',None),
        'user_id':data['user']['id'],'role':data['user']['role'],'portal':portal})
    return {'mfa_required': False, 'user': data['user'],'csrf_token':csrf}


@router.post('/mobile/login')
async def mobile_login(body: LoginRequest, request: Request,
                       session: AsyncSession = Depends(get_session)):
    """Native-client login sharing portal checks and refresh rotation with web."""
    try:
        data = await auth_service.login(session, str(body.email), body.password, body.portal,
            get_client_ip(request), request.headers.get('user-agent'))
    except RateLimitError as exc:
        await session.commit()
        raise HTTPException(429, str(exc)) from exc
    except AccountStatusError as exc:
        await session.commit()
        raise HTTPException(403, str(exc)) from exc
    except AuthError as exc:
        await session.commit()
        raise HTTPException(401, auth_service.GENERIC_INVALID) from exc
    if data.get('mfa_required'):
        mfa_portal = auth_service.decode_token(data['mfa_token']).get('portal')
        return {'mfa_required': True, 'mfa_token': data['mfa_token'], 'portal': mfa_portal}
    return {'mfa_required': False, 'access_token': data['access_token'],
        'refresh_token': data['refresh_token'], 'user': data['user']}


@router.post('/mobile/mfa/verify')
async def mobile_verify_mfa(body: MobileMfaVerifyRequest, request: Request,
                            session: AsyncSession = Depends(get_session)):
    try:
        data = await auth_service.verify_mfa(session, body.mfa_token, body.code, body.portal,
            get_client_ip(request), request.headers.get('user-agent'))
    except AuthError as exc:
        await session.commit()
        raise HTTPException(401, auth_service.GENERIC_INVALID) from exc
    return {'access_token': data['access_token'], 'refresh_token': data['refresh_token'],
        'user': data['user']}


@router.post('/mobile/refresh')
async def mobile_refresh(body: MobileRefreshRequest, request: Request,
                         session: AsyncSession = Depends(get_session)):
    try:
        data = await auth_service.rotate_refresh(session, body.refresh_token,
            get_client_ip(request), request.headers.get('user-agent'))
    except AuthError as exc:
        await session.commit()
        raise HTTPException(401, 'Session expired. Sign in again.') from exc
    return {'access_token': data['access_token'], 'refresh_token': data['refresh_token'],
        'user': data['user']}


@router.post('/mobile/logout', status_code=204)
async def mobile_logout(body: MobileLogoutRequest, request: Request,
                        session: AsyncSession = Depends(get_session)):
    await auth_service.logout(session, body.refresh_token, None, get_client_ip(request))
    return Response(status_code=204)


@router.post('/login')
async def shared_login(body: LoginRequest, request: Request, response: Response,
                       session: AsyncSession = Depends(get_session)):
    """Authenticate only when the stored role matches the selected portal."""
    return await _shared_login(body, request, response, session, body.portal)


@router.post('/login/institution', include_in_schema=False)
async def institution_login_compat(body: LoginCredentials, request: Request, response: Response,
                                   session: AsyncSession = Depends(get_session)):
    return await _shared_login(body, request, response, session, 'institution')


@router.post('/login/official', include_in_schema=False)
async def official_login_compat(body: LoginCredentials, request: Request, response: Response,
                                session: AsyncSession = Depends(get_session)):
    return await _shared_login(body, request, response, session, 'official')


@router.post('/login/admin', include_in_schema=False)
async def admin_login_compat(body: LoginCredentials, request: Request, response: Response,
                             session: AsyncSession = Depends(get_session)):
    return await _shared_login(body, request, response, session, 'admin')


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
    csrf=set_session_cookies(response, data)
    return {'user': data['user'],'csrf_token':csrf}


@router.post('/refresh')
async def refresh(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    raw = request.cookies.get(COOKIE_REFRESH)
    if not raw:
        failed=JSONResponse(status_code=401,content={'error':{'code':'INVALID_CREDENTIALS',
            'message':'Session expired. Sign in again.','request_id':getattr(request.state,'request_id',None)}})
        clear_session_cookies(failed)
        logger.info('auth_refresh_rejected',extra={'request_id':getattr(request.state,'request_id',None),
            'failure_category':'missing_refresh_cookie'})
        return failed
    try:
        data = await auth_service.rotate_refresh(session, raw, get_client_ip(request), request.headers.get('user-agent'))
    except AuthError as exc:
        await session.commit()
        failed = JSONResponse(status_code=401, content={'error': {'code': 'INVALID_CREDENTIALS', 'message': str(exc)}})
        clear_session_cookies(failed)
        logger.warning('auth_refresh_rejected',extra={'request_id':getattr(request.state,'request_id',None),
            'failure_category':'invalid_or_revoked_refresh'})
        return failed
    csrf=set_session_cookies(response, data)
    logger.info('auth_refresh_succeeded',extra={'request_id':getattr(request.state,'request_id',None),
        'user_id':data['user']['id'],'role':data['user']['role']})
    return {'user': data['user'],'csrf_token':csrf}


@router.post('/logout', status_code=204)
async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    await auth_service.logout(session, request.cookies.get(COOKIE_REFRESH), request.cookies.get(COOKIE_ACCESS), get_client_ip(request))
    clear_session_cookies(response)
    logger.info('auth_logout',extra={'request_id':getattr(request.state,'request_id',None)})
    response.status_code = 204
    return response


@router.get('/me')
async def me(user=Depends(get_current_user)):
    return auth_service.user_public(user)


@router.get('/csrf')
async def csrf_bootstrap(response: Response):
    """Issue/repair the readable CSRF cookie; auth cookies remain HttpOnly."""
    return {'csrf_token':set_csrf_cookie(response)}


@router.post('/change-password', status_code=204)
async def change_password(body: PasswordChangeRequest, request: Request, response: Response,
                          session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    try:
        auth_service.validate_password_strength(body.new_password, user.email, user.full_name)
        await auth_service.change_password(session, user, body.current_password, body.new_password, get_client_ip(request))
        clear_session_cookies(response)
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
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    return {'message': 'If the registration can be processed, it will be queued for administrator approval.'}


@router.post('/register/official', status_code=202)
async def register_official(body: OfficialRegistrationRequest, request: Request,
                            session: AsyncSession = Depends(get_session)):
    await auth_service.throttle_public_action(session, 'official_register', str(body.email), get_client_ip(request), 5, 60)
    try:
        await auth_service.register_official(session, body, get_client_ip(request))
    except IntegrityError:
        await session.rollback()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'message': 'If the application can be processed, it will be queued for Super Admin approval.'}


@router.post('/register/super-admin', status_code=201)
async def register_initial_super_admin(body: SuperAdminSetupRequest, request: Request,
                                       session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    if not settings.super_admin_setup_secret:
        raise HTTPException(503, 'Initial Super Admin setup is unavailable.')
    from app.services.rate_limit_service import enforce_rate_limit
    await enforce_rate_limit('super-admin-setup', get_client_ip(request), 5, 3600)
    from app.services.super_admin_setup_service import register_initial_super_admin as create_initial
    from sqlalchemy.exc import IntegrityError
    try:
        await create_initial(session, body)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, 'Initial Super Admin setup has already been completed or the email is unavailable.') from exc
    return {'message': 'Initial Super Admin account created. You can now sign in.'}


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
