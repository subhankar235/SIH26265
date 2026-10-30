"""Authorized workflow decisions, exception claims and safe node retry controls."""
from datetime import datetime, timezone
import html
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import AuthorizationState, ExecutionState, FDRStatus, LifecycleState, Role
from app.core.exceptions import InvalidStateTransition, NotFound
from app.models.fdr import FDR
from app.models.institution import Institution
from app.models.notification import Notification
from app.models.refund_request import RefundRequest
from app.models.user import User
from app.models.workflow import (ApprovalRecord, CorrectionRequest, ExceptionItem,
    WorkflowEvent, WorkflowInstance, WorkflowNodeExecution)
from app.schemas.workflow import ApprovalRequest
from app.services import fdr_service, refund_service
from app.services.audit_service import record
from app.services.outbox_service import enqueue as enqueue_outbox
from app.services.workflow_state_service import record_human_decision
from app.services.workflow_events import publish
from app.services import auth_service
from app.workflows.definition import NODES


def utcnow(): return datetime.now(timezone.utc)


async def _notify_institution_decision(session: AsyncSession, fdr: FDR, decision: str,
                                       rationale: str, idempotency_key: str) -> None:
    institution=await session.get(Institution,fdr.institution_id)
    if not institution or not institution.contact_email: return
    stage=f'OFFICIAL-DECISION-{idempotency_key[:80]}'
    if await session.scalar(select(Notification.id).where(Notification.fdr_id==fdr.id,
        Notification.stage==stage,Notification.channel=='email')): return
    safe_number=html.escape(fdr.fdr_number);safe_decision=html.escape(decision.replace('_',' ').title())
    safe_rationale=html.escape(rationale)
    notification=Notification(fdr_id=fdr.id,stage=stage,channel='email',recipient=institution.contact_email,status='queued')
    session.add(notification);await session.flush()
    await enqueue_outbox(session,str(fdr.id),'DELIVER_NOTIFICATION',
        {'notification_id':notification.id,'channel':'email','recipient':institution.contact_email,
         'subject':f'AICTE FDR review update: {fdr.fdr_number}',
         'body':f'<p>Decision for FDR {safe_number}: {safe_decision}.</p><p>Official remarks: {safe_rationale}</p>',
         'template_version':'official-decision-v1'},
        f'official-decision:{fdr.id}:{idempotency_key}:institution-email')


async def _resolve_case_exceptions(session: AsyncSession, workflow_id: int, actor: User) -> None:
    items=list((await session.scalars(select(ExceptionItem).where(
        ExceptionItem.workflow_instance_id==workflow_id,ExceptionItem.status!='resolved').with_for_update())).all())
    for item in items:
        previous=item.status;item.status='resolved';item.assigned_to=actor.id;item.resolved_at=utcnow()
        await record(session,actor.id,'exception',item.id,'EXCEPTION_RESOLVED_BY_DECISION','',
            {'status':[previous,'resolved']},institution_id=(await session.get(WorkflowInstance,workflow_id)).institution_id)
    corrections=list((await session.scalars(select(CorrectionRequest).where(
        CorrectionRequest.workflow_instance_id==workflow_id,CorrectionRequest.status=='open').with_for_update())).all())
    for correction in corrections:
        correction.status='accepted';correction.responded_at=utcnow();correction.resolved_by=actor.id


async def submit_approval(session: AsyncSession, actor: User, body: ApprovalRequest) -> dict:
    if actor.role!='aicte_official': raise InvalidStateTransition('Only an AICTE Official may record case decisions.')
    existing=await session.scalar(select(ApprovalRecord).where(ApprovalRecord.idempotency_key==body.idempotency_key))
    if existing:
        if existing.actor_user_id!=actor.id:
            raise InvalidStateTransition('IDEMPOTENCY_KEY_ACTOR_MISMATCH: key was used by another official.')
        return {'approval_id':existing.id,'workflow_id':existing.workflow_instance_id,
            'fdr_id':existing.fdr_id,'decision':existing.decision,'duplicate':True}
    fdr=await session.get(FDR,body.fdr_id)
    if not fdr: raise NotFound('FDR case not found.')
    workflow=await session.scalar(select(WorkflowInstance).where(WorkflowInstance.fdr_id==fdr.id)
        .order_by(WorkflowInstance.execution_version.desc()).limit(1).with_for_update())
    if not workflow: raise NotFound('FDR workflow was not found.')
    existing=await session.scalar(select(ApprovalRecord).where(ApprovalRecord.idempotency_key==body.idempotency_key))
    if existing:
        if existing.actor_user_id!=actor.id:
            raise InvalidStateTransition('IDEMPOTENCY_KEY_ACTOR_MISMATCH: key was used by another official.')
        return {'approval_id':existing.id,'workflow_id':existing.workflow_instance_id,
            'fdr_id':existing.fdr_id,'decision':existing.decision,'duplicate':True}
    if body.request_type=='release_refund':
        if not body.refund_request_id: raise InvalidStateTransition('A release/refund request id is required.')
        refund=await session.get(RefundRequest,body.refund_request_id)
        if not refund or refund.fdr_id!=fdr.id: raise NotFound('Release/refund request not found.')
        target={'approve':'approved','reject':'rejected'}.get(body.decision)
        if target is None: raise InvalidStateTransition('Release/refund supports approve or reject only.')
        if workflow.execution_state != ExecutionState.WAITING_HUMAN.value:
            raise InvalidStateTransition('Release/refund decision is not currently awaited.')
        result=await refund_service.decide(session,refund.id,target,body.rationale,actor.id)
        approval=await session.scalar(select(ApprovalRecord).where(ApprovalRecord.refund_request_id==result.id,
            ApprovalRecord.decision==body.decision).order_by(ApprovalRecord.id.desc()).limit(1))
        if approval: approval.idempotency_key=body.idempotency_key
        await _resolve_case_exceptions(session,workflow.id,actor)
        await record(session,actor.id,'workflow',workflow.id,'OFFICIAL_RELEASE_DECISION','',
            {'decision':[None,body.decision],'refund_request_id':[None,result.id],
             'rationale':[None,body.rationale]},institution_id=fdr.institution_id)
        return {'approval_id':approval.id if approval else None,'workflow_id':workflow.id,
            'fdr_id':fdr.id,'decision':body.decision,'duplicate':False}

    if workflow.execution_state != ExecutionState.WAITING_HUMAN.value:
        raise InvalidStateTransition('Official decision is not currently awaited for this case.')
    if body.decision == 'approve':
        target=FDRStatus.VERIFIED.value
    elif body.decision in {'reject','request_correction'}:
        target=FDRStatus.MISMATCH.value
    else:
        raise InvalidStateTransition('Escalation is an exception action; it is not an FDR approval decision.')
    # Legacy status transition may require an intermediate under-scrutiny status.
    await fdr_service.transition(session,fdr.id,target,actor.id,body.rationale,
        decision_override=body.decision,approval_idempotency_key=body.idempotency_key)
    approval=await session.scalar(select(ApprovalRecord).where(ApprovalRecord.fdr_id==fdr.id,
        ApprovalRecord.decision==body.decision).order_by(ApprovalRecord.id.desc()).limit(1))
    if approval: approval.idempotency_key=body.idempotency_key
    await _notify_institution_decision(session,fdr,body.decision,body.rationale,body.idempotency_key)
    if body.decision=='approve': await _resolve_case_exceptions(session,workflow.id,actor)
    # If correction is requested, the existing discrepancy/correction workflow is resumed
    # by a new document version. This decision is not applied automatically to funds.
    await record(session,actor.id,'workflow',workflow.id,'OFFICIAL_FDR_DECISION','',
        {'decision':[None,body.decision],'rationale':[None,body.rationale]},institution_id=fdr.institution_id)
    return {'approval_id':approval.id if approval else None,'workflow_id':workflow.id,
        'fdr_id':fdr.id,'decision':body.decision,'duplicate':False}


async def apply_exception_decision(session: AsyncSession, actor: User, exception_id: int,
                                   decision: str, rationale: str, idempotency_key: str) -> ExceptionItem:
    if actor.role!='aicte_official': raise InvalidStateTransition('Only an AICTE Official may decide case exceptions.')
    previous_approval=await session.scalar(select(ApprovalRecord).where(ApprovalRecord.idempotency_key==idempotency_key))
    if previous_approval:
        return await session.get(ExceptionItem,exception_id)
    previous_event=await session.scalar(select(WorkflowEvent).where(
        WorkflowEvent.dedupe_key==f'exception:{exception_id}:escalate:{idempotency_key}'))
    if previous_event:
        return await session.get(ExceptionItem,exception_id)
    item=await session.scalar(select(ExceptionItem).where(ExceptionItem.id==exception_id).with_for_update())
    if not item: raise NotFound('Exception not found.')
    if item.status=='resolved': raise InvalidStateTransition('Exception is already resolved.')
    workflow=await session.scalar(select(WorkflowInstance).where(
        WorkflowInstance.id==item.workflow_instance_id).with_for_update())
    fdr=await session.get(FDR,workflow.fdr_id)
    if decision in {'approve','reject','request_correction'}:
        mapped={'approve':'approve','reject':'reject','request_correction':'request_correction'}[decision]
        if fdr.status not in {FDRStatus.SUBMITTED.value,FDRStatus.UNDER_SCRUTINY.value,FDRStatus.MISMATCH.value}:
            raise InvalidStateTransition('This exception does not permit a scrutiny decision in the current FDR state.')
        if fdr.status==FDRStatus.MISMATCH.value and decision=='approve':
            target=FDRStatus.VERIFIED
        elif decision=='approve':
            target=FDRStatus.VERIFIED
        else: target=FDRStatus.MISMATCH
        await fdr_service.transition(session,fdr.id,target,actor.id,rationale,
            decision_override=mapped,approval_idempotency_key=idempotency_key)
        await _notify_institution_decision(session,fdr,decision,rationale,idempotency_key)
        if decision=='approve': await _resolve_case_exceptions(session,workflow.id,actor)
    elif decision=='escalate':
        workflow.lifecycle_state=LifecycleState.ESCALATED.value
        await publish(session,workflow.id,'OFFICIAL_ESCALATED_EXCEPTION',
            {'exception_id':item.id,'actor_user_id':actor.id,'rationale':rationale},
            f'exception:{item.id}:escalate:{idempotency_key}')
        await record(session,actor.id,'workflow',workflow.id,'OFFICIAL_ESCALATED_EXCEPTION','',
            {'exception_id':[None,item.id],'rationale':[None,rationale]},institution_id=workflow.institution_id)
    else:
        raise InvalidStateTransition('Unsupported exception decision.')
    item.status='resolved';item.resolved_at=auth_service.utcnow();item.assigned_to=actor.id
    await record(session,actor.id,'exception',item.id,'EXCEPTION_RESOLVED','',
        {'status':['open','resolved'],'decision':[None,decision],'rationale':[None,rationale]},
        institution_id=workflow.institution_id)
    return item


async def list_exceptions(session: AsyncSession, status: str | None, priority: int | None,
                          query: str | None, page) -> list[dict]:
    stmt=select(ExceptionItem,WorkflowInstance,FDR).join(WorkflowInstance,
        WorkflowInstance.id==ExceptionItem.workflow_instance_id).join(FDR,FDR.id==WorkflowInstance.fdr_id)
    if status: stmt=stmt.where(ExceptionItem.status==status)
    if priority is not None: stmt=stmt.where(ExceptionItem.priority<=priority)
    if query:
        from sqlalchemy import or_
        term=f'%{query.strip()}%'
        stmt=stmt.where(or_(FDR.fdr_number.ilike(term),ExceptionItem.reason_code.ilike(term)))
    rows=(await session.execute(stmt.order_by(ExceptionItem.priority,ExceptionItem.due_at,
        ExceptionItem.created_at).offset(page.skip).limit(page.limit))).all()
    result=[]
    for item,workflow,fdr in rows:
        result.append({'id':item.id,'workflow_id':workflow.id,'fdr_id':fdr.id,
            'fdr_number':fdr.fdr_number,'institution_id':fdr.institution_id,
            'reason_code':item.reason_code,'priority':item.priority,'due_at':item.due_at,
            'status':item.status,'evidence_refs':item.evidence_refs,
            'recommended_action':item.recommended_action,'assigned_to':item.assigned_to,
            'created_at':item.created_at})
    return result


async def claim_exception(session: AsyncSession, actor: User, exception_id: int, reason: str,
                          idempotency_key: str) -> ExceptionItem:
    if actor.role!='aicte_official': raise InvalidStateTransition('Only an AICTE Official may claim case exceptions.')
    previous=await session.scalar(select(WorkflowEvent).where(
        WorkflowEvent.dedupe_key==f'exception:{exception_id}:claim:{idempotency_key}'))
    if previous:return await session.get(ExceptionItem,exception_id)
    item=await session.scalar(select(ExceptionItem).where(ExceptionItem.id==exception_id).with_for_update())
    if not item: raise NotFound('Exception not found.')
    if item.status=='resolved': raise InvalidStateTransition('Resolved exceptions cannot be claimed.')
    if item.assigned_to not in (None,actor.id): raise InvalidStateTransition('Exception is already claimed by another official.')
    before={'status':item.status,'assigned_to':item.assigned_to}
    item.status='claimed';item.assigned_to=actor.id
    await record(session,actor.id,'exception',item.id,'EXCEPTION_CLAIMED','',
        {'status':[before['status'],item.status],'assigned_to':[before['assigned_to'],actor.id],'reason':[None,reason]},
        institution_id=(await session.get(WorkflowInstance,item.workflow_instance_id)).institution_id)
    await publish(session,item.workflow_instance_id,'EXCEPTION_CLAIMED',
        {'exception_id':item.id,'actor_user_id':actor.id,'reason':reason},
        f'exception:{exception_id}:claim:{idempotency_key}')
    return item


async def retry_failed_node(session: AsyncSession, workflow_id: int, node_execution_id: int,
                            actor: User, reason: str, idempotency_key: str,
                            acknowledge_side_effects: bool=False) -> WorkflowInstance:
    existing=await session.scalar(select(WorkflowEvent).where(WorkflowEvent.dedupe_key==f'workflow:{workflow_id}:retry:{idempotency_key}'))
    instance=await session.scalar(select(WorkflowInstance).where(WorkflowInstance.id==workflow_id).with_for_update())
    if not instance: raise NotFound('Workflow not found.')
    if existing: return instance
    if instance.execution_state in {ExecutionState.RUNNING.value,ExecutionState.RETRYING.value}:
        raise InvalidStateTransition('INSTANCE_BUSY: workflow is already executing.')
    if instance.execution_state not in {ExecutionState.BLOCKED.value,ExecutionState.FAILED.value}:
        raise InvalidStateTransition('Node retry requires a blocked/failed workflow; use checkpoint replay for other states.')
    node=await session.get(WorkflowNodeExecution,node_execution_id)
    if not node or node.workflow_instance_id!=instance.id or node.status!='failed':
        raise NotFound('Failed node execution not found.')
    definition=NODES.get(node.node_key)
    if not definition: raise InvalidStateTransition('Node is not part of this workflow version.')
    if definition.side_effect_class=='human_decision': raise InvalidStateTransition('REPLAY_NOT_ALLOWED: human decisions cannot be retried.')
    if definition.side_effect_class=='non_idempotent_effect' and not acknowledge_side_effects:
        raise InvalidStateTransition('SIDE_EFFECT_CONFIRMATION_REQUIRED: node may repeat a non-idempotent effect.')
    instance.retry_input_ref=node.input_ref or {}
    instance.retry_parent_execution_id=node.id
    instance.current_node=node.node_key
    instance.execution_state=ExecutionState.RETRYING.value
    instance.worker_lease_until=None;instance.next_wake_at=None;instance.version+=1
    await publish(session,instance.id,'WORKFLOW_NODE_RETRY_REQUESTED',
        {'node_execution_id':node.id,'actor_user_id':actor.id,'reason':reason,'idempotency_key':idempotency_key},
        f'workflow:{workflow_id}:retry:{idempotency_key}')
    await enqueue_outbox(session,str(instance.id),'WORKFLOW_WAKE',{'workflow_instance_id':instance.id,
        'retry_node_execution_id':node.id},f'outbox:workflow:{workflow_id}:retry:{idempotency_key}')
    await record(session,actor.id,'workflow_node_execution',node.id,'NODE_RETRY_REQUESTED','',
        {'reason':[None,reason],'execution_state':[ExecutionState.FAILED.value,ExecutionState.RETRYING.value]},
        institution_id=instance.institution_id)
    return instance


async def pause_workflow(session: AsyncSession, workflow_id: int, actor: User, reason: str,
                         idempotency_key: str | None = None) -> WorkflowInstance:
    instance=await session.scalar(select(WorkflowInstance).where(WorkflowInstance.id==workflow_id).with_for_update())
    if not instance: raise NotFound('Workflow not found.')
    if idempotency_key:
        prior=await session.scalar(select(WorkflowEvent).where(
            WorkflowEvent.dedupe_key==f'workflow:{workflow_id}:pause:{idempotency_key}'))
        if prior:return instance
    if instance.execution_state in {ExecutionState.COMPLETED.value,ExecutionState.CANCELLED.value,ExecutionState.BLOCKED.value}:
        raise InvalidStateTransition('This workflow state cannot be paused.')
    if instance.worker_lease_until and instance.worker_lease_until > datetime.now(timezone.utc):
        raise InvalidStateTransition('INSTANCE_BUSY: a worker node is currently executing.')
    previous=instance.execution_state
    instance.paused_from_state=previous;instance.execution_state=ExecutionState.PAUSED.value
    instance.paused_by=actor.id;instance.pause_reason=reason;instance.version+=1
    fdr=await session.get(FDR,instance.fdr_id);fdr.execution_state=instance.execution_state
    await record(session,actor.id,'workflow',instance.id,'WORKFLOW_PAUSED','',
        {'execution_state':[previous,instance.execution_state],'reason':[None,reason]},institution_id=instance.institution_id)
    await publish(session,instance.id,'WORKFLOW_PAUSED',{'actor_user_id':actor.id,'reason':reason},
        f'workflow:{workflow_id}:pause:{idempotency_key or instance.version}')
    return instance


async def resume_workflow(session: AsyncSession, workflow_id: int, actor: User, reason: str,
                          idempotency_key: str | None = None) -> WorkflowInstance:
    instance=await session.scalar(select(WorkflowInstance).where(WorkflowInstance.id==workflow_id).with_for_update())
    if not instance: raise NotFound('Workflow not found.')
    if idempotency_key:
        prior=await session.scalar(select(WorkflowEvent).where(
            WorkflowEvent.dedupe_key==f'workflow:{workflow_id}:resume:{idempotency_key}'))
        if prior:return instance
    if instance.execution_state != ExecutionState.PAUSED.value:
        raise InvalidStateTransition('Only paused workflows can be resumed.')
    previous=instance.paused_from_state or ExecutionState.RETRYING.value
    instance.execution_state=previous if previous in {ExecutionState.WAITING_EVENT.value,ExecutionState.WAITING_TIMER.value,ExecutionState.WAITING_HUMAN.value} else ExecutionState.RETRYING.value
    if instance.execution_state==ExecutionState.RETRYING.value and not instance.current_node:
        instance.current_node='extract_document'
    instance.paused_from_state=None;instance.paused_by=None;instance.pause_reason=None;instance.version+=1
    fdr=await session.get(FDR,instance.fdr_id);fdr.execution_state=instance.execution_state
    await record(session,actor.id,'workflow',instance.id,'WORKFLOW_RESUMED','',
        {'execution_state':[ExecutionState.PAUSED.value,instance.execution_state],'reason':[None,reason]},institution_id=instance.institution_id)
    await publish(session,instance.id,'WORKFLOW_RESUMED',{'actor_user_id':actor.id,'reason':reason},
        f'workflow:{workflow_id}:resume:{idempotency_key or instance.version}')
    if instance.execution_state==ExecutionState.RETRYING.value:
        await enqueue_outbox(session,str(instance.id),'WORKFLOW_WAKE',{'workflow_instance_id':instance.id},
            f'workflow:{instance.id}:resume:{instance.version}')
    return instance
