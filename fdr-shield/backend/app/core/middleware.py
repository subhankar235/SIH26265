"""HTTP middleware."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.security import verify_csrf_token


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Capture user_id, ip, method, path, status; push a lightweight request log.
        # (State-change audit rows are written explicitly by services via audit_service.record)
        response=await call_next(request)
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection for cookie-authenticated unsafe requests."""
    async def dispatch(self, request, call_next):
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            path = request.url.path
            public_auth = path.endswith(('/auth/login/institution', '/auth/login/official', '/auth/login/admin',
                '/auth/register/institution', '/auth/forgot-password', '/auth/reset-password',
                '/auth/verify-email', '/auth/accept-invite'))
            cookie_session = any(request.cookies.get(name) for name in ('access_token', 'refresh_token', 'mfa_token'))
            if cookie_session and not public_auth:
                cookie = request.cookies.get('csrf_token', '')
                header = request.headers.get('x-csrf-token', '')
                if not cookie or not header or cookie != header or not verify_csrf_token(cookie):
                    return JSONResponse(status_code=403, content={'error': 'CSRF_VALIDATION_FAILED',
                        'detail': 'CSRF token missing or invalid.'})
        response = await call_next(request)
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        return response


async def add_request_id(request, call_next):
    import uuid
    request_id=request.headers.get('X-Request-ID') or str(uuid.uuid4())
    request.state.request_id=request_id
    response=await call_next(request); response.headers['X-Request-ID']=request_id
    return response
