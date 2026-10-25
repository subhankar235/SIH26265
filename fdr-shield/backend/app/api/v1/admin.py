"""Admin-only account management and registration approvals."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import Pagination, get_current_user, pagination, require_roles
from app.core.enums import AccountStatus, Role
from app.core.exceptions import InvalidStateTransition
from app.models.user import User
from app.models.notification import Notification
from app.models.workflow import NotificationDeliveryAttempt, OutboxEvent
from app.schemas.auth import AdminUserCreate, AdminUserOut, AdminUserUpdate, RegistrationDecision
from app.services import user_admin_service

router = APIRouter()
ADMIN = require_roles(Role.ADMIN)


@router.get('/users', response_model=list[AdminUserOut])
async def list_users(role: str | None = None, status: str | None = None, q: str | None = None,
                     page: Pagination = Depends(pagination), session: AsyncSession = Depends(get_session),
                     actor=Depends(ADMIN)):
    return await user_admin_service.list_users(session, role, status, q, page)


@router.post('/users', response_model=AdminUserOut, status_code=201)
async def create_user(body: AdminUserCreate, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    try: return await user_admin_service.create_user(session, body, actor)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.patch('/users/{user_id}', response_model=AdminUserOut)
async def update_user(user_id: int, body: AdminUserUpdate, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    try: return await user_admin_service.update_user(session, user_id, body, actor)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post('/users/{user_id}/disable', response_model=AdminUserOut)
async def disable_user(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.set_user_active(session, user_id, False, actor)


@router.post('/users/{user_id}/enable', response_model=AdminUserOut)
async def enable_user(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.set_user_active(session, user_id, True, actor)


@router.post('/users/{user_id}/unlock', response_model=AdminUserOut)
async def unlock_user(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.unlock_user(session, user_id, actor)


@router.post('/users/{user_id}/reset-password', status_code=202)
async def reset_user_password(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    await user_admin_service.reset_user_password(session, user_id, actor)
    return {'queued': True}


@router.post('/users/{user_id}/revoke-sessions', status_code=204)
async def revoke_sessions(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    await user_admin_service.revoke_sessions(session, user_id, actor)


@router.get('/registrations', response_model=list[AdminUserOut])
async def pending_registrations(page: Pagination = Depends(pagination), session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.list_users(session, Role.INSTITUTION.value, AccountStatus.PENDING_APPROVAL.value, None, page)


@router.post('/registrations/{user_id}/approve', response_model=AdminUserOut)
async def approve_registration(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.approve_registration(session, user_id, True, None, actor)


@router.post('/registrations/{user_id}/reject', response_model=AdminUserOut)
async def reject_registration(user_id: int, body: RegistrationDecision, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    if not body.reason:
        raise HTTPException(422, 'A rejection reason is required.')
    return await user_admin_service.approve_registration(session, user_id, False, body.reason, actor)


@router.get('/notification-deliveries')
async def notification_deliveries(status: str | None = None, page: Pagination = Depends(pagination),
                                  session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    query = select(NotificationDeliveryAttempt).order_by(NotificationDeliveryAttempt.scheduled_at.desc())
    if status: query = query.where(NotificationDeliveryAttempt.status == status)
    attempts = list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
    result=[]
    for attempt in attempts:
        notification = await session.get(Notification, attempt.notification_id)
        result.append({'attempt_id':attempt.id,'notification_id':attempt.notification_id,
            'fdr_id':notification.fdr_id if notification else None,
            'stage':notification.stage if notification else None,'channel':attempt.provider,
            'recipient':notification.recipient if notification else None,'status':attempt.status,
            'attempt_no':attempt.attempt_no,'template_version':attempt.template_version,
            'scheduled_at':attempt.scheduled_at,'sent_at':attempt.sent_at,'error':attempt.error})
    return result


@router.get('/outbox')
async def outbox_status(status: str | None = None, page: Pagination = Depends(pagination),
                        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    query=select(OutboxEvent).order_by(OutboxEvent.created_at.desc())
    if status: query=query.where(OutboxEvent.status==status)
    rows=list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
    return [{'id':row.id,'aggregate_id':row.aggregate_id,'event_type':row.event_type,
        'status':row.status,'attempts':row.attempts,'next_attempt_at':row.next_attempt_at,
        'locked_until':row.locked_until,'last_error':row.last_error,'created_at':row.created_at} for row in rows]


@router.get('/workflow-health')
async def workflow_health(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from sqlalchemy import func
    from app.models.workflow import WorkflowInstance
    by_execution=dict((await session.execute(select(WorkflowInstance.execution_state,
        func.count(WorkflowInstance.id)).group_by(WorkflowInstance.execution_state))).all())
    dead_outbox=await session.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status=='dead'))
    pending_outbox=await session.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status.in_(['pending','failed','processing'])))
    return {'workflow_counts':by_execution,'outbox_dead':int(dead_outbox or 0),
        'outbox_pending_or_processing':int(pending_outbox or 0)}


@router.get('/workflow-failures')
async def workflow_failures(page: Pagination = Depends(pagination), session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.models.workflow import WorkflowInstance, WorkflowNodeExecution
    rows=(await session.execute(select(WorkflowInstance,WorkflowNodeExecution)
        .join(WorkflowNodeExecution,WorkflowNodeExecution.workflow_instance_id==WorkflowInstance.id)
        .where(WorkflowInstance.execution_state.in_(['blocked','failed']),WorkflowNodeExecution.status=='failed')
        .order_by(WorkflowNodeExecution.finished_at.desc()).offset(page.skip).limit(page.limit))).all()
    return [{'workflow_id':workflow.id,'fdr_id':workflow.fdr_id,'node_execution_id':node.id,
        'node_key':node.node_key,'error_class':node.error_class,'error_code':node.error_code,
        'error_message':node.error_message,'finished_at':node.finished_at} for workflow,node in rows]
