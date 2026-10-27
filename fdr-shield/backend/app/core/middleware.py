"""HTTP middleware."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.security import verify_csrf_token
from app.core.request_context import request_id_context
import logging
import time

logger=logging.getLogger('fdr_shield.http')


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        started=time.perf_counter();status_code=500
        try:
            response=await call_next(request)
            status_code=response.status_code
            return response
        finally:
            # Intentionally exclude query strings, bodies, cookies, headers, and user data.
            logger.info('http_request',extra={'request_id':getattr(request.state,'request_id',None),
                'method':request.method,'path':request.url.path,'status_code':status_code,
                'duration_ms':round((time.perf_counter()-started)*1000,2)})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection for cookie-authenticated unsafe requests."""
    async def dispatch(self, request, call_next):
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            path = request.url.path
            public_auth = path.endswith(('/auth/login', '/auth/login/institution', '/auth/login/official', '/auth/login/admin',
                '/auth/register/institution', '/auth/register/official', '/auth/register/super-admin', '/auth/forgot-password', '/auth/reset-password',
                '/auth/verify-email', '/auth/accept-invite'))
            cookie_session = any(request.cookies.get(name) for name in ('access_token', 'refresh_token', 'mfa_token'))
            if cookie_session and not public_auth:
                cookie = request.cookies.get('csrf_token', '')
                header = request.headers.get('x-csrf-token', '')
                if not cookie or not header or cookie != header or not verify_csrf_token(cookie):
                    logger.warning('csrf_validation_failed',extra={'request_id':getattr(request.state,'request_id',None),
                        'path':path})
                    return JSONResponse(status_code=403, content={'error': 'CSRF_VALIDATION_FAILED',
                        'detail': 'CSRF token missing or invalid.'})
        response = await call_next(request)
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        return response


async def add_request_id(request, call_next):
    import uuid
    supplied=request.headers.get('X-Request-ID','')
    request_id=supplied if len(supplied)<=64 and supplied.isascii() and all(c.isalnum() or c in '-_.' for c in supplied) else str(uuid.uuid4())
    request.state.request_id=request_id
    token=request_id_context.set(request_id)
    try:
        response=await call_next(request); response.headers['X-Request-ID']=request_id
        return response
    finally:
        request_id_context.reset(token)
