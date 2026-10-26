"""Alert history & manual send."""

from fastapi import APIRouter, Depends, Header
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles, pagination, Pagination
from app.services import notification_service, fdr_service
from app.core.enums import AlertStage
from fastapi import HTTPException
import asyncio
from sqlalchemy import select
from app.models.notification import Notification
from app.models.fdr import FDR
from app.models.workflow import NotificationDeliveryAttempt, OutboxEvent
from app.core.enums import Role
from app.services.audit_service import record
from datetime import datetime, timezone

router = APIRouter()


@router.get("")
async def list_notifications(fdr_id: int | None = None, status: str | None = None,
                             page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(get_current_user)):
    # Alert history
    scope=user.institution_id if user.role=='institution' else None
    return await notification_service.list_notifications(session,fdr_id,scope,page,status)


@router.get('/{notification_id}/attempts')
async def delivery_attempts(notification_id: int, session=Depends(get_session), user=Depends(get_current_user)):
    notification=await session.get(Notification,notification_id)
    if not notification: raise HTTPException(404,'Notification not found')
    fdr=await session.get(FDR,notification.fdr_id)
    if user.role=='institution' and fdr.institution_id!=user.institution_id:
        raise HTTPException(404,'Notification not found')
    if user.role not in {'institution','aicte_official','admin'}:
        raise HTTPException(403,'Not authorized to inspect notification attempts.')
    rows=list((await session.scalars(select(NotificationDeliveryAttempt).where(
        NotificationDeliveryAttempt.notification_id==notification_id)
        .order_by(NotificationDeliveryAttempt.attempt_no))).all())
    return [{'id':row.id,'attempt_no':row.attempt_no,'provider':row.provider,'status':row.status,
        'scheduled_at':row.scheduled_at,'sent_at':row.sent_at,
        'error':row.error if user.role!='institution' else None,
        'provider_response':row.provider_response if user.role in {'aicte_official','admin'} else None} for row in rows]


@router.post("/test")
async def send_test_alert(fdr_id: int, stage: str, session=Depends(get_session), user=Depends(require_roles('admin'))):
    # Demo helper: fire T-90/T-30/T-0 immediately for judges
    await fdr_service.get_fdr(session,fdr_id)
    try: parsed=AlertStage(stage)
    except ValueError as exc:raise HTTPException(422,'Unknown alert stage') from exc
    from app.workers.tasks_maturity import send_alert_task
    await asyncio.to_thread(send_alert_task.delay,fdr_id,parsed.value)
    return {'queued':True,'fdr_id':fdr_id,'stage':parsed.value}


@router.post('/{notification_id}/retry')
async def retry_notification(notification_id: int, idempotency_key: str = Header(...,alias='Idempotency-Key',min_length=8,max_length=255),
                             session=Depends(get_session), user=Depends(require_roles(Role.ADMIN))):
    notification=await session.get(Notification,notification_id)
    if not notification: raise HTTPException(404,'Notification not found')
    if notification.status!='failed': raise HTTPException(409,'Only failed delivery intents may be manually retried.')
    original=await session.scalar(select(OutboxEvent).where(
        OutboxEvent.event_type=='DELIVER_NOTIFICATION',
        OutboxEvent.payload['notification_id'].as_integer()==notification.id,
        OutboxEvent.status.in_(['dead','failed'])).order_by(OutboxEvent.id.desc()).limit(1))
    if not original: raise HTTPException(404,'Failed delivery outbox item not found')
    fdr=await session.get(FDR,notification.fdr_id)
    retry_key=f'admin-notification-retry:{notification.id}:{idempotency_key}'
    if await session.scalar(select(OutboxEvent.id).where(OutboxEvent.idempotency_key==retry_key)):
        return {'queued':True,'notification_id':notification.id,'duplicate':True}
    original_status=original.status
    notification.status='queued';notification.sent_at=None
    from app.services.outbox_service import enqueue as enqueue_outbox
    await enqueue_outbox(session,str(notification.fdr_id),'DELIVER_NOTIFICATION',original.payload,retry_key)
    await record(session,user.id,'notification',notification.id,'DELIVERY_RETRY_REQUESTED','',
        {'outbox_status':[original_status,'queued'],'retry_operator':[None,user.id],'idempotency_key':[None,idempotency_key]},
        institution_id=fdr.institution_id if fdr else None)
    return {'queued':True,'notification_id':notification.id}
