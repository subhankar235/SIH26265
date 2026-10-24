from dataclasses import dataclass
from typing import Callable
from fastapi import Depends, Request, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.security import decode_token
from app.models.user import User

oauth2_scheme=OAuth2PasswordBearer(tokenUrl='/api/v1/auth/login')
@dataclass
class Pagination:
    skip:int=0
    limit:int=20
def pagination(page:int=1,size:int=20)->Pagination: return Pagination(max(0,page-1)*min(max(size,1),100),min(max(size,1),100))
async def get_current_user(token:str=Depends(oauth2_scheme), session:AsyncSession=Depends(get_session))->User:
    try: claims=decode_token(token)
    except Exception as e: raise HTTPException(401,'Invalid credentials') from e
    if claims.get('mfa_pending'): raise HTTPException(401,'MFA verification required')
    user=await session.scalar(select(User).where(User.id==int(claims['sub'])))
    if not user or not user.is_active: raise HTTPException(401,'Inactive or unknown user')
    return user
def require_roles(*roles)->Callable:
    async def check(user=Depends(get_current_user)):
        if user.role not in [getattr(r,'value',r) for r in roles]: raise HTTPException(403,'Insufficient role')
        return user
    return check
def get_client_ip(request:Request)->str:
    return request.headers.get('x-forwarded-for','').split(',')[0].strip() or (request.client.host if request.client else 'unknown')
