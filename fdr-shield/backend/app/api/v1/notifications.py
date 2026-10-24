"""Alert history & manual send."""

from fastapi import APIRouter, Depends
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles, pagination, Pagination
from app.services import notification_service, fdr_service
from app.core.enums import AlertStage
from fastapi import HTTPException
import asyncio

router = APIRouter()


@router.get("")
async def list_notifications(fdr_id: int | None = None, page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(get_current_user)):
    # Alert history
    scope=user.institution_id if user.role=='institution' else None
    return await notification_service.list_notifications(session,fdr_id,scope,page)


@router.post("/test")
async def send_test_alert(fdr_id: int, stage: str, session=Depends(get_session), user=Depends(require_roles('admin'))):
    # Demo helper: fire T-90/T-30/T-0 immediately for judges
    await fdr_service.get_fdr(session,fdr_id)
    try: parsed=AlertStage(stage)
    except ValueError as exc:raise HTTPException(422,'Unknown alert stage') from exc
    from app.workers.tasks_maturity import send_alert_task
    await asyncio.to_thread(send_alert_task.delay,fdr_id,parsed.value)
    return {'queued':True,'fdr_id':fdr_id,'stage':parsed.value}
