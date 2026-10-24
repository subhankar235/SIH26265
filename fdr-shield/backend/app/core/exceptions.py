"""Domain exceptions and their HTTP handlers."""

from fastapi import FastAPI


class AuthError(Exception): ...


class PermissionDenied(Exception): ...


class NotFound(Exception): ...


class InvalidStateTransition(Exception): ...


def register_exception_handlers(app: FastAPI) -> None:
    from fastapi.responses import JSONResponse
    from starlette import status
    mapping={AuthError:401,PermissionDenied:403,NotFound:404,InvalidStateTransition:409}
    for error, code in mapping.items():
        async def handler(request, exc, code=code, error=error):
            return JSONResponse(status_code=code,content={'error':error.__name__,'detail':str(exc)})
        app.add_exception_handler(error,handler)
