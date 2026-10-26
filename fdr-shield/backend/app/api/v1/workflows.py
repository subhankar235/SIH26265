"""Workflow control-room inspection, progress stream and safe recovery APIs."""
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session, SessionLocal
from app.core.deps import Pagination, get_current_user, pagination, require_roles
from app.core.enums import ExecutionState, Role
from app.core.exceptions import InvalidStateTransition, NotFound
from app.models.fdr import FDR
from app.models.user import User
from app.models.workflow import WorkflowCheckpoint, WorkflowEvent, WorkflowInstance, WorkflowNodeExecution
from app.schemas.workflow import ReplayRequest, RetryNodeRequest, WorkflowActionRequest
from app.schemas.workflow import ApprovalRequest, ExceptionClaimRequest, ExceptionDecisionRequest
from app.services import workflow_action_service as actions
from app.services.workflow_state_service import replay_from_checkpoint, start_new_execution

router=APIRouter()
OFFICIAL_ADMIN=require_roles(Role.AICTE_OFFICIAL,Role.ADMIN)
OFFICIAL=require_roles(Role.AICTE_OFFICIAL)


async def _scoped_workflow(session, workflow_id: int, user):
    instance=await session.get(WorkflowInstance,workflow_id)
    if not instance or (user.role=='institution' and instance.institution_id!=user.institution_id):
        raise NotFound('Workflow not found.')
    return instance


@router.get('')
async def list_workflows(lifecycle_state: str | None=None, execution_state: str | None=None,
                         institution_id: int | None=None, page: Pagination=Depends(pagination),
                         session: AsyncSession=Depends(get_session),user=Depends(get_current_user)):
    query=select(WorkflowInstance,FDR.is_synthetic).join(FDR,FDR.id==WorkflowInstance.fdr_id).order_by(WorkflowInstance.updated_at.desc())
    if lifecycle_state: query=query.where(WorkflowInstance.lifecycle_state==lifecycle_state)
    if execution_state: query=query.where(WorkflowInstance.execution_state==execution_state)
    if user.role=='institution': query=query.where(WorkflowInstance.institution_id==user.institution_id)
    elif institution_id: query=query.where(WorkflowInstance.institution_id==institution_id)
    rows=list((await session.execute(query.offset(page.skip).limit(page.limit))).all())
    return [{'id':row.id,'fdr_id':row.fdr_id,'institution_id':row.institution_id,
        'workflow_version':row.workflow_version,'execution_version':row.execution_version,
        'lifecycle_state':row.lifecycle_state,'execution_state':row.execution_state,
        'authorization_state':row.authorization_state,'current_node':row.current_node,
        'next_wake_at':row.next_wake_at,'updated_at':row.updated_at,'is_synthetic':is_synthetic} for row,is_synthetic in rows]


@router.get('/recommendations')
async def workflow_recommendations(session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    from app.services.ml_service import official_recommendations
    return await official_recommendations(session)


@router.get('/exceptions')
async def exception_inbox(status: str | None=None, priority: int | None=None, q: str | None=None,
                          page: Pagination=Depends(pagination),session: AsyncSession=Depends(get_session),
                          user=Depends(OFFICIAL)):
    return await actions.list_exceptions(session,status,priority,q,page)


@router.post('/exceptions/{exception_id}/claim')
async def claim_exception(exception_id: int,body: ExceptionClaimRequest,
                          session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    item=await actions.claim_exception(session,user,exception_id,body.reason,body.idempotency_key)
    return {'id':item.id,'status':item.status,'assigned_to':item.assigned_to}


@router.post('/exceptions/{exception_id}/decision')
async def decide_exception(exception_id: int,body: ExceptionDecisionRequest,
                           session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    item=await actions.apply_exception_decision(session,user,exception_id,body.decision,
        body.rationale,body.idempotency_key)
    return {'id':item.id,'status':item.status,'decision':body.decision}


@router.post('/approvals')
async def create_approval(body: ApprovalRequest,session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    return await actions.submit_approval(session,user,body)


@router.get('/{workflow_id:int}')
async def get_workflow(workflow_id: int, session: AsyncSession=Depends(get_session),
                       user=Depends(get_current_user)):
    instance=await _scoped_workflow(session,workflow_id,user)
    fdr_origin=await session.scalar(select(FDR.is_synthetic).where(FDR.id==instance.fdr_id))
    nodes=list((await session.scalars(select(WorkflowNodeExecution).where(
        WorkflowNodeExecution.workflow_instance_id==workflow_id).order_by(WorkflowNodeExecution.id))).all())
    events=list((await session.scalars(select(WorkflowEvent).where(
        WorkflowEvent.workflow_instance_id==workflow_id).order_by(WorkflowEvent.id))).all())
    checkpoints=list((await session.scalars(select(WorkflowCheckpoint).where(
        WorkflowCheckpoint.workflow_instance_id==workflow_id).order_by(WorkflowCheckpoint.id))).all())
    institution_view=user.role=='institution'
    return {'id':instance.id,'fdr_id':instance.fdr_id,'institution_id':instance.institution_id,'is_synthetic':fdr_origin,
        'workflow_version':instance.workflow_version,'execution_version':instance.execution_version,
        'lifecycle_state':instance.lifecycle_state,'execution_state':instance.execution_state,
        'authorization_state':instance.authorization_state,'current_node':instance.current_node,
        'next_wake_at':instance.next_wake_at,
        'nodes':[{'id':node.id,'node_key':node.node_key,'attempt':node.attempt,'status':node.status,
            'input_ref':node.input_ref if not institution_view else None,
            'output_ref':node.output_ref if not institution_view else None,
            'error_class':node.error_class if not institution_view else None,
            'error_code':node.error_code,'error_message':node.error_message,
            'started_at':node.started_at,'finished_at':node.finished_at,'duration_ms':node.duration_ms,
            'parent_execution_id':node.parent_execution_id,'replay_of_id':node.replay_of_id} for node in nodes],
        'events':[{'id':event.id,'event_type':event.event_type,'payload':event.payload if not institution_view else {},
            'received_at':event.received_at,'processed_at':event.processed_at} for event in events],
        'checkpoints':[{'id':cp.id,'node_execution_id':cp.node_execution_id,
            'schema_version':cp.schema_version,'created_at':cp.created_at} for cp in checkpoints]}


@router.get('/{workflow_id}/executions')
async def list_executions(workflow_id: int, node: str | None=None, status: str | None=None,
                          page: Pagination=Depends(pagination),session: AsyncSession=Depends(get_session),
                          user=Depends(OFFICIAL_ADMIN)):
    await _scoped_workflow(session,workflow_id,user)
    query=select(WorkflowNodeExecution).where(WorkflowNodeExecution.workflow_instance_id==workflow_id)
    if node: query=query.where(WorkflowNodeExecution.node_key==node)
    if status: query=query.where(WorkflowNodeExecution.status==status)
    rows=list((await session.scalars(query.order_by(WorkflowNodeExecution.id.desc()).offset(page.skip).limit(page.limit))).all())
    return [{'id':row.id,'node_key':row.node_key,'attempt':row.attempt,'status':row.status,
        'error_class':row.error_class,'error_code':row.error_code,'started_at':row.started_at,
        'finished_at':row.finished_at,'duration_ms':row.duration_ms,
        'parent_execution_id':row.parent_execution_id,'replay_of_id':row.replay_of_id} for row in rows]


@router.get('/executions/{execution_id}')
async def get_execution(execution_id: int,session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL_ADMIN)):
    node=await session.get(WorkflowNodeExecution,execution_id)
    if not node: raise NotFound('Node execution not found.')
    await _scoped_workflow(session,node.workflow_instance_id,user)
    return {'id':node.id,'workflow_id':node.workflow_instance_id,'node_key':node.node_key,
        'attempt':node.attempt,'status':node.status,'input_ref':node.input_ref,'output_ref':node.output_ref,
        'input_hash':node.input_hash,'error_class':node.error_class,'error_code':node.error_code,
        'error_message':node.error_message,'diagnostics':node.diagnostics,'started_at':node.started_at,
        'finished_at':node.finished_at,'duration_ms':node.duration_ms,'workflow_version':node.workflow_version,
        'parent_execution_id':node.parent_execution_id,'replay_of_id':node.replay_of_id,
        'reason':node.reason,'actor_user_id':node.actor_user_id}


@router.get('/{workflow_id}/compare')
async def compare_runs(workflow_id: int,a: int,b: int,session: AsyncSession=Depends(get_session),
                       user=Depends(OFFICIAL)):
    await _scoped_workflow(session,workflow_id,user)
    left=await session.get(WorkflowNodeExecution,a);right=await session.get(WorkflowNodeExecution,b)
    if not left or not right or left.workflow_instance_id!=workflow_id or right.workflow_instance_id!=workflow_id:
        raise NotFound('Execution comparison target not found.')
    return {'left':a,'right':b,'node_key':left.node_key,'same_node':left.node_key==right.node_key,
        'input_equal':left.input_ref==right.input_ref,'output_equal':left.output_ref==right.output_ref,
        'left_status':left.status,'right_status':right.status,'left_error':left.error_message,
        'right_error':right.error_message}


@router.post('/{workflow_id}/pause')
async def pause(workflow_id: int,body: WorkflowActionRequest,session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    instance=await actions.pause_workflow(session,workflow_id,user,body.reason,body.idempotency_key)
    return {'workflow_id':instance.id,'execution_state':instance.execution_state,'paused_by':instance.paused_by}


@router.post('/{workflow_id}/resume')
async def resume(workflow_id: int,body: WorkflowActionRequest,session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    instance=await actions.resume_workflow(session,workflow_id,user,body.reason,body.idempotency_key)
    return {'workflow_id':instance.id,'execution_state':instance.execution_state}


@router.post('/{workflow_id}/new-version',status_code=202)
async def new_version(workflow_id: int,body: WorkflowActionRequest,session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    instance=await _scoped_workflow(session,workflow_id,user)
    fdr=await session.get(FDR,instance.fdr_id)
    fresh=await start_new_execution(session,fdr,user.id,body.reason,body.idempotency_key)
    return {'workflow_id':fresh.id,'execution_version':fresh.execution_version,'queued':True}


@router.post('/executions/{execution_id}/retry',status_code=202)
async def retry_node(execution_id: int,body: RetryNodeRequest,session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    node=await session.get(WorkflowNodeExecution,execution_id)
    if not node: raise NotFound('Node execution not found.')
    instance=await actions.retry_failed_node(session,node.workflow_instance_id,node.id,user,
        body.reason,body.idempotency_key,body.acknowledge_side_effects)
    return {'workflow_id':instance.id,'execution_state':instance.execution_state,'retry_node':node.node_key}


@router.post('/{workflow_id}/replay',status_code=202)
async def replay_workflow(workflow_id: int,body: ReplayRequest,session: AsyncSession=Depends(get_session),
                          user=Depends(OFFICIAL)):
    instance=await replay_from_checkpoint(session,workflow_id,body.checkpoint_id,user.id,
        user.role,body.reason,body.acknowledge_side_effects,body.idempotency_key)
    return {'queued':True,'workflow_id':instance.id,'checkpoint_id':body.checkpoint_id,
        'current_node':instance.current_node,'execution_state':instance.execution_state}


@router.post('/{workflow_id}/retry',status_code=202)
async def retry_workflow_node(workflow_id: int,body: RetryNodeRequest,
                              node_execution_id: int=Query(...),
                              session: AsyncSession=Depends(get_session),user=Depends(OFFICIAL)):
    instance=await _scoped_workflow(session,workflow_id,user)
    result=await actions.retry_failed_node(session,workflow_id,node_execution_id,user,
        body.reason,body.idempotency_key,body.acknowledge_side_effects)
    return {'queued':True,'workflow_id':result.id,'execution_state':result.execution_state}


@router.get('/{workflow_id}/events')
async def workflow_events(workflow_id: int, after: int = 0, page: Pagination = Depends(pagination),
                          session: AsyncSession = Depends(get_session), user = Depends(get_current_user)):
    await _scoped_workflow(session, workflow_id, user)
    rows = list((await session.scalars(select(WorkflowEvent).where(
        WorkflowEvent.workflow_instance_id == workflow_id, WorkflowEvent.id > after)
        .order_by(WorkflowEvent.id).offset(page.skip).limit(page.limit))).all())
    institution_view = user.role == 'institution'
    return [{'id': row.id, 'type': row.event_type,
             'payload': row.payload if not institution_view else {k: v for k, v in (row.payload or {}).items() if not k.startswith('_') and k not in {'diagnostics', 'error_class'}},
             'received_at': row.received_at, 'processed_at': row.processed_at} for row in rows]


@router.get('/{workflow_id}/stream')
async def stream_workflow(workflow_id: int, request: Request, after: int = 0,
                          session: AsyncSession = Depends(get_session), user = Depends(get_current_user)):
    instance = await _scoped_workflow(session, workflow_id, user)
    # 8.3 Client reconnect with Last-Event-ID
    last_event_id = request.headers.get('last-event-id') or request.query_params.get('last_event_id')
    if last_event_id and str(last_event_id).isdigit():
        after = max(after, int(last_event_id))

    from app.services.event_bus import get_event_bus
    bus = get_event_bus()
    institution_view = user.role == 'institution'

    def sanitize_payload(payload: dict) -> dict:
        if not institution_view:
            return payload
        # 8.4 Per-event scope filter: institution isolation strips internal diagnostics
        return {k: v for k, v in (payload or {}).items() if not k.startswith('_') and k not in {'diagnostics', 'error_class', 'raw_ref'}}

    async def stream():
        cursor = after
        # 8.3 Replay from workflow_event table
        async with SessionLocal() as replay_session:
            history = list((await replay_session.scalars(select(WorkflowEvent).where(
                WorkflowEvent.workflow_instance_id == workflow_id,
                WorkflowEvent.id > cursor
            ).order_by(WorkflowEvent.id).limit(200))).all())
        for event in history:
            cursor = event.id
            safe_payload = sanitize_payload(event.payload)
            yield f'id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(safe_payload, default=str)}\n\n'

        channel = f"workflow:{workflow_id}"
        async for broadcast_event in bus.subscribe(channel):
            if await request.is_disconnected():
                return

            # Live user and authorization revocation check
            async with SessionLocal() as check_session:
                live_user = await check_session.get(User, user.id)
                state = await check_session.get(WorkflowInstance, workflow_id)

            if not live_user or not live_user.is_active or live_user.status != 'active' or not state:
                yield 'event: stream.revoked\ndata: {}\n\n'
                return

            # 8.4 Institution isolation check
            if live_user.role == 'institution' and state.institution_id != live_user.institution_id:
                yield 'event: stream.revoked\ndata: {}\n\n'
                return

            if broadcast_event is None:
                # Periodic heartbeat
                yield ': heartbeat\n\n'
                # Check if terminal state reached
                if state and state.execution_state in {
                    ExecutionState.COMPLETED.value, ExecutionState.BLOCKED.value,
                    ExecutionState.FAILED.value, ExecutionState.CANCELLED.value
                }:
                    yield 'event: stream.complete\ndata: {}\n\n'
                    return
                continue

            # Dedup already replayed events
            if broadcast_event.id is not None and broadcast_event.id <= cursor:
                continue

            event_id_str = f"id: {broadcast_event.id}\n" if broadcast_event.id is not None else ""
            if broadcast_event.id is not None:
                cursor = broadcast_event.id
            safe_payload = sanitize_payload(broadcast_event.payload)
            yield f"{event_id_str}event: {broadcast_event.event_type}\ndata: {json.dumps(safe_payload, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@router.get('/exceptions/stream')
async def stream_exceptions(request: Request, after: int = 0,
                            user = Depends(OFFICIAL), session: AsyncSession = Depends(get_session)):
    # 8.3 Client reconnect with Last-Event-ID
    last_event_id = request.headers.get('last-event-id') or request.query_params.get('last_event_id')
    if last_event_id and str(last_event_id).isdigit():
        after = max(after, int(last_event_id))

    from app.services.event_bus import get_event_bus
    from app.services.workflow_events import EXCEPTIONS_INBOX_EVENTS
    bus = get_event_bus()

    async def inbox_stream():
        cursor = after
        # 8.3 Replay existing exception events
        async with SessionLocal() as replay_session:
            history = list((await replay_session.scalars(select(WorkflowEvent).where(
                WorkflowEvent.id > cursor,
                WorkflowEvent.event_type.in_(EXCEPTIONS_INBOX_EVENTS)
            ).order_by(WorkflowEvent.id).limit(100))).all())
        for event in history:
            cursor = event.id
            yield f'id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(event.payload, default=str)}\n\n'

        async for broadcast_event in bus.subscribe("inbox:exceptions"):
            if await request.is_disconnected():
                return

            async with SessionLocal() as check_session:
                live_user = await check_session.get(User, user.id)

            if not live_user or not live_user.is_active or live_user.status != 'active' or live_user.role not in {'aicte_official', 'admin'}:
                yield 'event: stream.revoked\ndata: {}\n\n'
                return

            if broadcast_event is None:
                yield ': heartbeat\n\n'
                continue

            if broadcast_event.id is not None and broadcast_event.id <= cursor:
                continue

            event_id_str = f"id: {broadcast_event.id}\n" if broadcast_event.id is not None else ""
            if broadcast_event.id is not None:
                cursor = broadcast_event.id
            yield f"{event_id_str}event: {broadcast_event.event_type}\ndata: {json.dumps(broadcast_event.payload, default=str)}\n\n"

    return StreamingResponse(
        inbox_stream(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )
