"""Manual triggers & results for OCR / bank verification (USP 1 & 3)."""

from fastapi import APIRouter, Depends, BackgroundTasks
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles
from app.core.deps import pagination, Pagination
from app.services import verification_service

router = APIRouter()


@router.post("/{fdr_id}/run")
async def run_verification(fdr_id: int, background_tasks: BackgroundTasks, session=Depends(get_session), user=Depends(require_roles('scrutiny_officer','bureau_chief'))):
    # Re-enqueue verification task
    from app.workers.tasks_verification import run_verification_pipeline
    background_tasks.add_task(run_verification_pipeline.delay,fdr_id)
    return {'queued':True}


@router.get("/{fdr_id}/report")
async def get_report(fdr_id: int, session=Depends(get_session), user=Depends(get_current_user)):
    # Return VerificationReport (ocr, bank, discrepancies, trust badge)
    scope=user.institution_id if user.role=='institution' else None
    return await verification_service.get_report(session,fdr_id,scope)


@router.post("/discrepancies/{discrepancy_id}/resolve")
async def resolve_discrepancy(discrepancy_id: int, remarks: str, session=Depends(get_session), user=Depends(require_roles('scrutiny_officer','bureau_chief'))):
    # Mark resolved, recompute badge, audit
    return await verification_service.resolve_discrepancy(session,discrepancy_id,remarks,user.id,getattr(user,'email',''))


@router.get("/discrepancies")
async def list_discrepancies(resolved: bool = False, page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(require_roles('scrutiny_officer','bureau_chief','admin'))):
    # Discrepancy Alert Board data
    return await verification_service.list_discrepancies(session,resolved,page)
