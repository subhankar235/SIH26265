"""Release / refund workflow."""

from fastapi import APIRouter, Depends
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles
from app.schemas.refund import RefundCreate, RefundDecision
from app.services import refund_service
from app.core.deps import pagination, Pagination

router = APIRouter()


@router.post("")
async def create_refund(body: RefundCreate, session=Depends(get_session), user=Depends(require_roles('institution'))):
    # Only allowed if FDR VERIFIED and matured/obligation closed
    return await refund_service.create_refund(session,body,user.id,user.institution_id)


@router.get("")
async def list_refunds(status: str | None = None, page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(require_roles('institution','aicte_official','admin'))):
    # Institution: own; bureau: all
    scope=user.institution_id if user.role=='institution' else None
    return await refund_service.list_refunds(session,status,scope,page)


@router.post("/{refund_id}/decision")
async def decide_refund(refund_id: int, body: RefundDecision, session=Depends(get_session), user=Depends(require_roles('aicte_official'))):
    # Approve/reject; on approve set FDR RELEASED; audit
    return await refund_service.decide(session,refund_id,body.decision,body.remarks,user.id,body.idempotency_key)
