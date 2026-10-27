from dataclasses import dataclass
from typing import Callable
from datetime import datetime, timezone
from fastapi import Depends, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.security import decode_token
from app.models.user import User
from app.models.institution import Institution
from app.models.auth_records import RefreshToken

@dataclass
class Pagination:
    skip:int=0
    limit:int=20
def pagination(page:int=1,size:int=20)->Pagination: return Pagination(max(0,page-1)*min(max(size,1),100),min(max(size,1),100))
async def get_current_user(request: Request, session:AsyncSession=Depends(get_session))->User:
    token = request.cookies.get('access_token')
    if not token:
        raise HTTPException(401, 'Authentication required')
    try: claims=decode_token(token)
    except Exception as e: raise HTTPException(401,'Invalid credentials') from e
    try:
        user_id=int(claims['sub'])
    except (TypeError,ValueError) as exc:
        raise HTTPException(401,'Invalid credentials') from exc
    user=await session.scalar(select(User).where(User.id==user_id))
    if not user or not await is_current_access_session(session,user,claims):
        raise HTTPException(401,'Inactive or unknown user')
    return user


async def is_current_access_session(session:AsyncSession,user:User,claims:dict)->bool:
    """Recheck database-backed authorization for requests and long-lived SSE streams."""
    if (claims.get('typ')!='access' or claims.get('mfa_pending') or
            claims.get('sub')!=str(user.id) or claims.get('role')!=user.role or
            claims.get('ver',0)!=user.session_version or not user.is_active or user.status!='active'):
        return False
    family_id=claims.get('sid')
    if family_id:
        active_family=await session.scalar(select(RefreshToken.id).where(
            RefreshToken.user_id==user.id,RefreshToken.family_id==family_id,
            RefreshToken.revoked_at.is_(None),RefreshToken.expires_at>datetime.now(timezone.utc)))
        if not active_family:return False
    if user.role=='institution':
        institution_status=await session.scalar(select(Institution.status).where(Institution.id==user.institution_id))
        if institution_status!='active':return False
    return True
def require_roles(*roles)->Callable:
    async def check(user=Depends(get_current_user)):
        if user.role not in [getattr(r,'value',r) for r in roles]: raise HTTPException(403,'Insufficient role')
        return user
    return check
def get_client_ip(request:Request)->str:
    from app.core.config import get_settings
    peer = request.client.host if request.client else 'unknown'
    trusted = {value.strip() for value in get_settings().trusted_proxy_ips.split(',') if value.strip()}
    forwarded = request.headers.get('x-forwarded-for', '')
    if peer in trusted and forwarded:
        return forwarded.split(',')[0].strip() or peer
    return peer
