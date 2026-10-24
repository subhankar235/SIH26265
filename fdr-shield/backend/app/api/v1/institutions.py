"""Institution CRUD (bureau) and self-profile (institution)."""

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles
from app.schemas.institution import InstitutionCreate
from app.services import institution_service
from app.core.deps import pagination, Pagination
from fastapi import HTTPException

router = APIRouter()


@router.get("")
async def list_institutions(q: str | None = None, state: str | None = None, page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(require_roles('aicte_official','admin'))):
    # Paginated search; include fdr_count and total_value
    return await institution_service.search_institutions(session,q,state,page)


@router.post("")
async def create_institution(body: InstitutionCreate, session=Depends(get_session), user=Depends(require_roles('admin'))):
    # Create institution + default institution user
    return await institution_service.create_institution(session,body)


@router.get("/{institution_id}")
async def get_institution(institution_id: int, session=Depends(get_session), user=Depends(get_current_user)):
    # Return detail; institution users may only read their own
    if user.role=='institution' and user.institution_id!=institution_id: raise HTTPException(404,'Institution not found')
    return await institution_service.get_institution(session,institution_id)


@router.get("/{institution_id}/fdrs")
async def institution_fdrs(institution_id: int, page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(get_current_user)):
    # All FDRs for institution (institution-wise record maintenance)
    if user.role=='institution' and user.institution_id!=institution_id: raise HTTPException(404,'Institution not found')
    return await institution_service.list_institution_fdrs(session,institution_id,page)
