"""Escalation scheduler (USP 2)."""

from .celery_app import celery_app, run_async_task
from datetime import date
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.fdr import FDR
from app.core.enums import FDRStatus
from app.services import notification_service
from app.services.audit_service import record


@celery_app.task(name='app.workers.tasks_maturity.scan_maturities')
def scan_maturities() -> None:
    # @celery_app.task (daily). Query ACTIVE FDRs with maturity <= today+90d
    # for each: stage = notification_service.stage_for(days_left)
    # if stage and stage != fdr.last_alert_stage: dispatch_alert + update last_alert_stage
    # if T-0 and no renewal: escalate_to_bureau
    # mark EXPIRED if maturity < today and not renewed
    run_async_task(_scan())


@celery_app.task(name='app.workers.tasks_maturity.send_alert_task')
def send_alert_task(fdr_id: int, stage: str) -> None:
    # @celery_app.task wrapper used by manual /notifications/test endpoint
    run_async_task(_send(fdr_id,stage))

async def _scan():
    async with SessionLocal() as session:
        relevant_statuses=[FDRStatus.VERIFIED.value,FDRStatus.SUBMITTED.value,FDRStatus.UNDER_SCRUTINY.value,FDRStatus.MISMATCH.value,FDRStatus.EXPIRED.value]
        rows=(await session.scalars(select(FDR).where(FDR.status.in_(relevant_statuses),FDR.maturity_date<=date.fromordinal(date.today().toordinal()+90)).order_by(FDR.maturity_date))).all()
        for f in rows:
            days=(f.maturity_date-date.today()).days
            if days<0 and f.status not in (FDRStatus.EXPIRED.value,FDRStatus.RENEWAL_REQUESTED.value,FDRStatus.RELEASED.value):
                previous=f.status;f.status=FDRStatus.EXPIRED.value
                await record(session,None,'fdr',f.id,'expired','scheduler',{'status':[previous,f.status]})
            stage=await notification_service.stage_for(days)
            if stage and f.last_alert_stage!=stage.value:
                await notification_service.dispatch_alert(session,f,stage)
                if stage.value=='T-0':await notification_service.escalate_to_bureau(session,f)
        await session.commit()
async def _send(fdr_id,stage):
    async with SessionLocal() as session:
        f=await session.get(FDR,fdr_id)
        if f: await notification_service.dispatch_alert(session,f,stage);await session.commit()
