"""Read-only audit trail."""

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles
from app.core.deps import pagination, Pagination
from app.services.audit_service import query_logs

router = APIRouter()


@router.get("")
async def list_audit_logs(entity: str | None = None, entity_id: int | None = None, user_id: int | None = None, page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(require_roles('bureau_chief','admin'))):
    # Paginated, filterable; NO write endpoints exist
    return await query_logs(session,{'entity':entity,'entity_id':entity_id,'user_id':user_id},page)
