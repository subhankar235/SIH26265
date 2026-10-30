"""Manual triggers & results for OCR / bank verification (USP 1 & 3)."""

from fastapi import APIRouter, Depends, Query, Header
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles
from app.core.deps import pagination, Pagination
from app.core.config import get_settings
from app.services import verification_service
from app.services.fdr_service import get_fdr
from app.services.workflow_state_service import start_new_execution
from app.models.workflow import WorkflowInstance
from sqlalchemy import select

router = APIRouter()


@router.post("/{fdr_id}/run")
async def run_verification(fdr_id: int, reason: str = Query('AICTE Official requested a verification reprocess.', min_length=4, max_length=1000),
                           idempotency_key: str = Header(...,alias='Idempotency-Key',min_length=8,max_length=255),
                           session=Depends(get_session), user=Depends(require_roles('aicte_official'))):
    # Reprocessing starts a new durable execution version and preserves prior node history.
    fdr = await get_fdr(session, fdr_id)
    if get_settings().celery_task_always_eager:
        latest = await session.scalar(select(WorkflowInstance).where(
            WorkflowInstance.fdr_id == fdr_id
        ).order_by(WorkflowInstance.execution_version.desc()).limit(1))
        if latest and latest.execution_state in {'running', 'retrying'}:
            from app.services.local_execution_service import run_inline_workflow_if_enabled
            await run_inline_workflow_if_enabled(session, fdr_id, resume_active=True)
            await session.refresh(latest)
            return {'queued':False,'workflow_id':latest.id,
                    'execution_version':latest.execution_version,
                    'execution_state':latest.execution_state,'resumed':True}
    instance = await start_new_execution(session, fdr, user.id, reason, idempotency_key)
    from app.services.local_execution_service import run_inline_workflow_if_enabled
    ran_inline = await run_inline_workflow_if_enabled(session, fdr_id)
    if ran_inline:
        await session.refresh(instance)
    return {'queued':not ran_inline,'workflow_id':instance.id,'execution_version':instance.execution_version,
            'execution_state':instance.execution_state}


@router.get("/{fdr_id}/report")
async def get_report(fdr_id: int, session=Depends(get_session), user=Depends(get_current_user)):
    # Return VerificationReport (ocr, bank, discrepancies, trust badge)
    scope=user.institution_id if user.role=='institution' else None
    return await verification_service.get_report(session,fdr_id,scope,
        include_review_assessment=user.role in {'aicte_official', 'admin'})


@router.post("/discrepancies/{discrepancy_id}/resolve")
async def resolve_discrepancy(discrepancy_id: int, remarks: str, session=Depends(get_session), user=Depends(require_roles('aicte_official'))):
    # Mark resolved, recompute badge, audit
    return await verification_service.resolve_discrepancy(session,discrepancy_id,remarks,user.id,getattr(user,'email',''))


@router.get("/discrepancies")
<<<<<<< HEAD
async def list_discrepancies(resolved: bool = False, real_only: bool = False,
        page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(require_roles('aicte_official','admin'))):
=======
async def list_discrepancies(resolved: bool = False, page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(require_roles('aicte_official','admin'))):
>>>>>>> a27ee110f6ba3d79cb2eb0cff239996b7f97ea26
    # Discrepancy Alert Board data
    return await verification_service.list_discrepancies(session,resolved,page,real_only)
