"""Institution CRUD (bureau), self-profile (institution), and Assistant Agent (Agent A)."""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles, pagination, Pagination, get_client_ip
from app.core.enums import Role
from app.schemas.institution import AssistantMessageRequest, AssistantMessageResponse, InstitutionCreate
from app.services import institution_service
from app.services import institution_assistant_service

router = APIRouter()


@router.get("")
async def list_institutions(
    q: str | None = None,
    state: str | None = None,
    page: Pagination = Depends(pagination),
    session = Depends(get_session),
    user = Depends(require_roles('aicte_official', 'admin'))
):
    # Paginated search; include fdr_count and total_value
    return await institution_service.search_institutions(session, q, state, page)


@router.post("")
async def create_institution(
    body: InstitutionCreate,
    session = Depends(get_session),
    user = Depends(require_roles('admin'))
):
    # Create institution and invite its initial account holder.
    return await institution_service.create_institution(session, body, user)


# Phase 10: Step 10.1 - POST /institution/assistant/messages (caller's own cases only)
@router.post("/assistant/messages", response_model=AssistantMessageResponse)
async def assistant_messages(
    body: AssistantMessageRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    if user.role not in {Role.INSTITUTION.value, Role.AICTE_OFFICIAL.value, Role.ADMIN.value}:
        raise HTTPException(403, 'Institution Assistant is only accessible to authenticated users.')
    if user.role == Role.INSTITUTION.value and not user.institution_id:
        raise HTTPException(404, 'User has no associated institution.')
    from app.services.rate_limit_service import enforce_rate_limit
    from app.core.config import get_settings
    await enforce_rate_limit('institution-assistant',f'{user.id}:{get_client_ip(request)}',get_settings().rate_limit_assistant_per_minute,60)
    return await institution_assistant_service.process_institution_message(
        session, user, body.message, body.fdr_ref
    )


@router.get('/ml/recommendations')
async def institution_ml_recommendations(fdr_id: int | None = None,
        session: AsyncSession = Depends(get_session), user=Depends(require_roles(Role.INSTITUTION))):
    if not user.institution_id:
        raise HTTPException(404, 'Institution not found')
    from app.services.ml_service import institution_recommendations
    return await institution_recommendations(session, user.institution_id, fdr_id)


@router.get("/{institution_id}")
async def get_institution(
    institution_id: int,
    session = Depends(get_session),
    user = Depends(get_current_user)
):
    # Return detail; institution users may only read their own
    if user.role == 'institution' and user.institution_id != institution_id:
        raise HTTPException(404, 'Institution not found')
    return await institution_service.get_institution(session, institution_id)


@router.get("/{institution_id}/fdrs")
async def institution_fdrs(
    institution_id: int,
    page: Pagination = Depends(pagination),
    session = Depends(get_session),
    user = Depends(get_current_user)
):
    # All FDRs for institution (institution-wise record maintenance)
    if user.role == 'institution' and user.institution_id != institution_id:
        raise HTTPException(404, 'Institution not found')
    return await institution_service.list_institution_fdrs(session, institution_id, page)
