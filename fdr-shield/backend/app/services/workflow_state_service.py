"""Compatibility mapping from legacy FDR status to explicit lifecycle dimensions."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import (AuthorizationState, ExecutionState, FDRStatus,
    LifecycleState, VerificationLevel)
from app.models.fdr import FDR
from app.models.workflow import WorkflowCheckpoint, WorkflowInstance, WorkflowEvent
from app.services.audit_service import record
from app.services.workflow_events import publish
from app.services.outbox_service import enqueue as enqueue_outbox
from app.workflows.transitions import transition as workflow_transition


LEGACY_STATUS_TO_LIFECYCLE = {
    FDRStatus.SUBMITTED.value: LifecycleState.SUBMITTED.value,
    FDRStatus.UNDER_SCRUTINY.value: LifecycleState.UNDER_REVIEW.value,
    FDRStatus.VERIFIED.value: LifecycleState.ACCEPTED.value,
    FDRStatus.MISMATCH.value: LifecycleState.CORRECTION_REQUIRED.value,
    FDRStatus.RENEWAL_REQUESTED.value: LifecycleState.RENEWAL_REQUIRED.value,
    FDRStatus.EXPIRED.value: LifecycleState.EXPIRED.value,
    FDRStatus.RELEASE_REQUESTED.value: LifecycleState.AWAITING_RELEASE_DECISION.value,
    FDRStatus.RELEASED.value: LifecycleState.RELEASE_APPROVED.value,
}


def authorization_for_legacy_status(status: str) -> str:
    if status in {FDRStatus.VERIFIED.value, FDRStatus.RELEASED.value}:
        return AuthorizationState.APPROVED.value
    if status in {FDRStatus.UNDER_SCRUTINY.value, FDRStatus.MISMATCH.value,
                  FDRStatus.RENEWAL_REQUESTED.value, FDRStatus.RELEASE_REQUESTED.value}:
        return AuthorizationState.PENDING.value
    return AuthorizationState.NOT_REQUIRED.value


def verification_level_for_fdr(fdr: FDR) -> str:
    if fdr.verification_level:
        return fdr.verification_level
    if fdr.bank_data and fdr.bank_data.get('found'):
        # The only bank adapter currently wired into this repository is mock-only.
        return VerificationLevel.MOCK_VERIFIED.value
    if fdr.ocr_data:
        return VerificationLevel.EXTRACTED.value
    return VerificationLevel.DECLARED.value


def source_verification_level_for_fdr(fdr: FDR) -> str:
    """Infer only the source level supported by legacy stored inputs, not human approval."""
    if fdr.bank_data and fdr.bank_data.get('found'):
        return VerificationLevel.MOCK_VERIFIED.value
    if fdr.ocr_data:
        return VerificationLevel.EXTRACTED.value
    return VerificationLevel.DECLARED.value


_VERIFICATION_RANK = {
    VerificationLevel.DECLARED.value: 0,
    VerificationLevel.AI_RECOMMENDATION.value: 0,
    VerificationLevel.EXTRACTED.value: 1,
    VerificationLevel.MOCK_VERIFIED.value: 2,
    VerificationLevel.VERIFIED_EXTERNAL.value: 3,
    VerificationLevel.HUMAN_SCRUTINIZED.value: 4,
}


def strongest_verification_level(current: str | None, candidate: str) -> str:
    """Do not let a later weak/missing check erase stronger recorded evidence."""
    if current is None or _VERIFICATION_RANK.get(candidate, 0) > _VERIFICATION_RANK.get(current, 0):
        return candidate
    return current


async def get_or_create_workflow(session: AsyncSession, fdr: FDR) -> WorkflowInstance:
    instance = await session.scalar(select(WorkflowInstance)
        .where(WorkflowInstance.fdr_id == fdr.id)
        .order_by(WorkflowInstance.execution_version.desc())
        .limit(1))
    if instance:
        fdr.execution_state = instance.execution_state
        fdr.authorization_state = instance.authorization_state
        return instance
    lifecycle = LEGACY_STATUS_TO_LIFECYCLE.get(fdr.status, LifecycleState.SUBMITTED.value)
    instance = WorkflowInstance(fdr_id=fdr.id, institution_id=fdr.institution_id,
        workflow_version='fdr-case-v1', execution_version=1, lifecycle_state=lifecycle,
        execution_state=ExecutionState.NOT_STARTED.value,
        authorization_state=authorization_for_legacy_status(fdr.status))
    session.add(instance)
    await session.flush()
    fdr.execution_state = instance.execution_state
    fdr.authorization_state = instance.authorization_state
    return instance


async def sync_legacy_status(session: AsyncSession, fdr: FDR, *, actor_id: int | None = None,
                             event_type: str = 'FDR_STATUS_SYNCHRONIZED',
                             previous_status: str | None = None,
                             lifecycle_override: str | None = None,
                             authorization_override: str | None = None) -> WorkflowInstance:
    lifecycle = lifecycle_override or LEGACY_STATUS_TO_LIFECYCLE.get(fdr.status, LifecycleState.SUBMITTED.value)
    instance = await get_or_create_workflow(session, fdr)
    if event_type == 'OFFICIAL_FDR_DECISION':
        transition_event = 'OFFICIAL_APPROVED' if fdr.status == FDRStatus.VERIFIED.value else 'OFFICIAL_REQUESTED_CORRECTION'
        lifecycle, instance.execution_state = workflow_transition(instance, transition_event, actor_role='aicte_official')
        instance.completed_at = None
        instance.current_node = None
        instance.worker_lease_until = None
    elif event_type == 'OFFICIAL_REVIEW_STARTED':
        lifecycle, instance.execution_state = workflow_transition(instance, 'OFFICIAL_REVIEW_STARTED', actor_role='aicte_official')
        instance.current_node = None
        instance.worker_lease_until = None
    elif event_type == 'RELEASE_REQUESTED':
        lifecycle, instance.execution_state = workflow_transition(instance, 'RELEASE_REQUESTED')
        instance.authorization_state = AuthorizationState.PENDING.value
        instance.current_node = None
        instance.worker_lease_until = None
    elif event_type in {'RELEASE_APPROVED','RELEASE_REJECTED'}:
        transition_event = event_type
        lifecycle, instance.execution_state = workflow_transition(instance, transition_event, actor_role='aicte_official')
        instance.completed_at = datetime.now(timezone.utc) if instance.execution_state == ExecutionState.COMPLETED.value else None
        instance.current_node = None
        instance.worker_lease_until = None
    elif event_type == 'FDR_RENEWAL_REQUESTED':
        lifecycle, instance.execution_state = workflow_transition(instance, 'RENEWAL_REQUESTED')
        instance.authorization_state = AuthorizationState.PENDING.value
        instance.current_node = None
        instance.worker_lease_until = None
        instance.worker_lease_until = None
    fdr.lifecycle_state = lifecycle
    fdr.verification_level = verification_level_for_fdr(fdr)
    instance.lifecycle_state = lifecycle
    instance.authorization_state = authorization_override or authorization_for_legacy_status(fdr.status)
    fdr.execution_state = instance.execution_state
    fdr.authorization_state = instance.authorization_state
    instance.version += 1
    event_key = f'workflow:{instance.id}:version:{instance.version}:{event_type}'
    inserted = await publish(session, instance.id, event_type, {
            'fdr_id': fdr.id,
            'previous_legacy_status': previous_status,
            'legacy_status': fdr.status,
            'lifecycle_state': lifecycle,
            'authorization_state': instance.authorization_state,
            'verification_level': fdr.verification_level,
            'actor_user_id': actor_id,
        }, event_key)
    if inserted and instance.execution_state in {ExecutionState.NOT_STARTED.value, ExecutionState.RUNNING.value, ExecutionState.RETRYING.value}:
        await enqueue_outbox(session, str(instance.id), 'WORKFLOW_WAKE',
            {'workflow_instance_id': instance.id, 'event_key': event_key},
            f'workflow-wake:{event_key}')
    return instance


async def record_human_decision(session: AsyncSession, fdr: FDR, actor_id: int,
                                actor_role: str, decision: str, rationale: str,
                                request_type: str = 'fdr_scrutiny',
                                refund_request_id: int | None = None,
                                idempotency_key: str | None = None) -> None:
    from app.models.workflow import ApprovalRecord
    instance = await get_or_create_workflow(session, fdr)
    if idempotency_key:
        existing = await session.scalar(select(ApprovalRecord).where(ApprovalRecord.idempotency_key == idempotency_key))
        if existing: return
    session.add(ApprovalRecord(workflow_instance_id=instance.id, fdr_id=fdr.id,
        refund_request_id=refund_request_id, request_type=request_type, decision=decision,
        rationale=rationale, actor_user_id=actor_id, actor_role=actor_role,
        idempotency_key=idempotency_key))
    await publish(session,instance.id,'approval.recorded',{'fdr_id':fdr.id,'actor_user_id':actor_id,
        'decision':decision,'request_type':request_type},
        f'approval:{instance.id}:{idempotency_key or f"{actor_id}{int(datetime.now(timezone.utc).timestamp())}"}')


async def start_new_execution(session: AsyncSession, fdr: FDR, actor_id: int, reason: str,
                              idempotency_key: str | None = None) -> WorkflowInstance:
    """Start an auditable, versioned reprocess; previous workflow history stays immutable."""
    if idempotency_key:
        prior_event=await session.scalar(select(WorkflowEvent).where(
            WorkflowEvent.dedupe_key==f'fdr:{fdr.id}:new-execution:{idempotency_key}'))
        if prior_event:
            prior_id=(prior_event.payload or {}).get('workflow_id')
            prior=await session.get(WorkflowInstance,prior_id) if prior_id else None
            if prior:return prior
    latest = await session.scalar(select(WorkflowInstance).where(WorkflowInstance.fdr_id == fdr.id)
        .order_by(WorkflowInstance.execution_version.desc()).limit(1).with_for_update())
    if latest and latest.execution_state in {ExecutionState.RUNNING.value, ExecutionState.RETRYING.value}:
        from app.core.exceptions import InvalidStateTransition
        raise InvalidStateTransition('A workflow execution is already running for this FDR.')
    version = (latest.execution_version if latest else 0) + 1
    instance = WorkflowInstance(fdr_id=fdr.id, institution_id=fdr.institution_id,
        workflow_version='fdr-case-v1', execution_version=version,
        lifecycle_state=LifecycleState.EXTRACTION_PENDING.value,
        execution_state=ExecutionState.NOT_STARTED.value,
        authorization_state=AuthorizationState.NOT_REQUIRED.value,
        current_node=None)
    session.add(instance)
    await session.flush()
    fdr.lifecycle_state = LifecycleState.EXTRACTION_PENDING.value
    fdr.execution_state = ExecutionState.NOT_STARTED.value
    event_key = f'fdr:{fdr.id}:new-execution:{idempotency_key or version}'
    await publish(session,instance.id,'MANUAL_REPROCESS_REQUESTED',
        {'fdr_id': fdr.id, 'workflow_id':instance.id, 'actor_user_id': actor_id, 'reason': reason},event_key)
    await enqueue_outbox(session, str(instance.id), 'WORKFLOW_WAKE',
        {'workflow_instance_id': instance.id}, f'outbox:{event_key}')
    await record(session, actor_id, 'workflow', instance.id, 'NEW_EXECUTION_VERSION', '',
        {'execution_version': [latest.execution_version if latest else None, version], 'reason': [None, reason]},
        institution_id=fdr.institution_id)
    return instance


async def replay_from_checkpoint(session: AsyncSession, workflow_id: int, checkpoint_id: int,
                                 actor_id: int, actor_role: str, reason: str,
                                 acknowledge_side_effects: bool = False,
                                 idempotency_key: str | None = None) -> WorkflowInstance:
    from app.core.exceptions import InvalidStateTransition, NotFound
    from app.models.workflow import WorkflowNodeExecution
    from app.workflows.definition import NODES, downstream_nodes
    instance = await session.scalar(select(WorkflowInstance).where(
        WorkflowInstance.id == workflow_id).with_for_update())
    if idempotency_key:
        prior_event=await session.scalar(select(WorkflowEvent).where(
            WorkflowEvent.dedupe_key==f'workflow:{workflow_id}:replay-request:{idempotency_key}'))
        if prior_event: return instance
    checkpoint = await session.get(WorkflowCheckpoint, checkpoint_id)
    if not instance or not checkpoint or checkpoint.workflow_instance_id != workflow_id:
        raise NotFound('Workflow checkpoint not found.')
    if actor_role != 'aicte_official':
        raise InvalidStateTransition('Only an AICTE Official can replay workflow nodes.')
    if instance.execution_state in {ExecutionState.RUNNING.value, ExecutionState.RETRYING.value}:
        raise InvalidStateTransition('INSTANCE_BUSY: workflow is already executing.')
    if instance.execution_state in {ExecutionState.COMPLETED.value,ExecutionState.CANCELLED.value}:
        raise InvalidStateTransition('Completed or cancelled workflows cannot be replayed.')
    original = await session.get(WorkflowNodeExecution, checkpoint.node_execution_id) if checkpoint.node_execution_id else None
    if not original or original.node_key not in NODES:
        raise InvalidStateTransition('Checkpoint does not point to a replayable workflow node.')
    downstream=downstream_nodes(original.node_key)
    classifications={node_key:NODES[node_key].side_effect_class for node_key in downstream}
    if any(value=='human_decision' for value in classifications.values()):
        raise InvalidStateTransition('REPLAY_NOT_ALLOWED: replay cannot cross a human-decision node.')
    unsafe=[key for key,value in classifications.items() if value=='non_idempotent_effect']
    if unsafe and not acknowledge_side_effects:
        raise InvalidStateTransition('SIDE_EFFECT_CONFIRMATION_REQUIRED: replay may repeat non-idempotent effects: '+','.join(unsafe))
    classification=NODES[original.node_key].side_effect_class
    snapshot = checkpoint.state_snapshot or {}
    input_ref = snapshot.get('input_ref') or {}
    output = snapshot.get('output') or {}
    document_id = (input_ref.get('document_id') or output.get('document_id') or
        (original.input_ref or {}).get('document_id'))
    if not document_id:
        raise InvalidStateTransition('Checkpoint lacks a versioned document reference.')
    if not await session.get(__import__('app.models.document', fromlist=['Document']).Document, int(document_id)):
        raise InvalidStateTransition('Checkpoint document version is no longer available.')
    instance.current_node = original.node_key
    instance.execution_state = ExecutionState.RETRYING.value
    instance.worker_lease_until = None
    instance.next_wake_at = None
    instance.replay_document_id = int(document_id)
    instance.replay_from_execution_id = original.id
    instance.replay_requested_by = actor_id
    instance.replay_reason = reason
    instance.version += 1
    event_key = f'workflow:{workflow_id}:replay-request:{idempotency_key or instance.version}'
    await publish(session, workflow_id, 'WORKFLOW_REPLAY_REQUESTED',
        {'checkpoint_id': checkpoint_id, 'node_key': original.node_key,
         'actor_user_id': actor_id, 'reason': reason,
         'side_effect_class': classification, 'downstream_side_effects':classifications,
         'acknowledged':acknowledge_side_effects,'document_id': int(document_id)}, event_key)
    await enqueue_outbox(session, str(workflow_id), 'WORKFLOW_WAKE',
        {'workflow_instance_id': workflow_id, 'replay_checkpoint_id': checkpoint_id},
        f'outbox:{event_key}')
    await record(session, actor_id, 'workflow', workflow_id, 'WORKFLOW_REPLAY_REQUESTED', '',
        {'checkpoint_id': [None, checkpoint_id], 'node_key': [None, original.node_key],
         'reason': [None, reason], 'document_id': [None, int(document_id)]},
        institution_id=instance.institution_id)
    return instance
