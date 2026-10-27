"""Domain exceptions and their HTTP handlers."""

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError


class AuthError(Exception): ...


class AccountStatusError(Exception): ...


class RateLimitError(Exception): ...


class PermissionDenied(Exception): ...


class NotFound(Exception): ...


class InvalidStateTransition(Exception): ...


def register_exception_handlers(app: FastAPI) -> None:
    from fastapi.responses import JSONResponse
    from starlette import status
    mapping={AuthError:401,RateLimitError:429,PermissionDenied:403,NotFound:404,InvalidStateTransition:409}
    for error, code in mapping.items():
        async def handler(request, exc, code=code, error=error):
            if error is AuthError:
                return JSONResponse(status_code=code, content={'error': {'code': 'INVALID_CREDENTIALS', 'message': str(exc),
                    'request_id':getattr(request.state,'request_id',None)}})
            if error is RateLimitError:
                return JSONResponse(status_code=code, content={'error': {'code': 'RATE_LIMITED', 'message': str(exc),
                    'details':{},'request_id':getattr(request.state,'request_id',None)}})
            if error is InvalidStateTransition:
                message=str(exc)
                error_code=next((candidate for candidate in ('INSTANCE_BUSY','SIDE_EFFECT_CONFIRMATION_REQUIRED','REPLAY_NOT_ALLOWED') if message.startswith(candidate)), 'ILLEGAL_TRANSITION')
                return JSONResponse(status_code=code,content={'error':{'code':error_code,'message':message,
                    'details':{},'request_id':getattr(request.state,'request_id',None)}})
            return JSONResponse(status_code=code,content={'error':error.__name__,'detail':str(exc),
                'request_id':getattr(request.state,'request_id',None)})
        app.add_exception_handler(error,handler)

    async def account_status_handler(request, exc: AccountStatusError):
        return JSONResponse(status_code=403, content={'error': {
            'code': 'ACCOUNT_STATUS', 'message': str(exc),
            'request_id': getattr(request.state, 'request_id', None)}})
    app.add_exception_handler(AccountStatusError, account_status_handler)

    async def http_error_handler(request, exc: HTTPException):
        codes={401:'UNAUTHENTICATED',403:'FORBIDDEN',404:'NOT_FOUND',409:'ILLEGAL_TRANSITION',
               422:'VALIDATION_ERROR',429:'RATE_LIMITED'}
        detail=exc.detail
        if isinstance(detail,dict) and 'error' in detail:
            code=detail.get('error',codes.get(exc.status_code,'HTTP_ERROR'))
            message=detail.get('detail',str(detail))
        else:
            code=codes.get(exc.status_code,'HTTP_ERROR');message=str(detail)
        return JSONResponse(status_code=exc.status_code,content={'error':{'code':code,'message':message,
            'details':{},'request_id':getattr(request.state,'request_id',None)}})

    async def validation_error_handler(request, exc: RequestValidationError):
        errors=[{'field':'.'.join(str(part) for part in item.get('loc',())[1:]),
            'message':item.get('msg','Invalid value')} for item in exc.errors()]
        return JSONResponse(status_code=422,content={'error':{'code':'VALIDATION_ERROR',
            'message':'Request validation failed.','details':{'fields':errors},
            'request_id':getattr(request.state,'request_id',None)}})

    app.add_exception_handler(HTTPException,http_error_handler)
    app.add_exception_handler(RequestValidationError,validation_error_handler)
