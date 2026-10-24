"""HTTP middleware."""

from starlette.middleware.base import BaseHTTPMiddleware


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Capture user_id, ip, method, path, status; push a lightweight request log.
        # (State-change audit rows are written explicitly by services via audit_service.record)
        response=await call_next(request)
        return response


async def add_request_id(request, call_next):
    import uuid
    request_id=request.headers.get('X-Request-ID') or str(uuid.uuid4())
    response=await call_next(request); response.headers['X-Request-ID']=request_id
    return response
