"""Authentication endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles
from app.schemas.auth import LoginRequest, MfaVerifyRequest
from app.services import auth_service

router = APIRouter()


@router.post("/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    # Verify password; if user has MFA -> return temp token + mfa_required=True else full JWT
    return await auth_service.login(session,body.email,body.password)


@router.post("/mfa/verify")
async def verify_mfa(body: MfaVerifyRequest, session=Depends(get_session)):
    # Validate TOTP; issue full JWT
    return await auth_service.verify_mfa(session,body.temp_token,body.code)


@router.post("/mfa/setup")
async def setup_mfa(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return await auth_service.setup_mfa(session,user)


@router.get("/me")
async def me(user=Depends(get_current_user)):
    # Return current user profile + role
    return {'id':user.id,'email':user.email,'role':user.role,'institution_id':user.institution_id}
