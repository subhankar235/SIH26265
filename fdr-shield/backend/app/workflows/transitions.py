"""Allowed workflow state transitions. Guard checks remain deterministic."""
from app.core.enums import AuthorizationState, ExecutionState, LifecycleState
from app.core.exceptions import InvalidStateTransition

ALLOWED = {
    (ExecutionState.NOT_STARTED.value, 'START'): (LifecycleState.EXTRACTION_PENDING.value, ExecutionState.RUNNING.value),
    (ExecutionState.NOT_STARTED.value, 'OFFICIAL_REVIEW_STARTED'): (LifecycleState.UNDER_REVIEW.value, ExecutionState.WAITING_HUMAN.value),
    (ExecutionState.RUNNING.value, 'NODE_STARTED'): (None, ExecutionState.RUNNING.value),
    (ExecutionState.RUNNING.value, 'NODE_SUCCEEDED'): (None, ExecutionState.RUNNING.value),
    (ExecutionState.RUNNING.value, 'NEEDS_CORRECTION'): (LifecycleState.AWAITING_INSTITUTION.value, ExecutionState.WAITING_EVENT.value),
    (ExecutionState.RUNNING.value, 'READY_FOR_REVIEW'): (LifecycleState.READY_FOR_SCRUTINY.value, ExecutionState.WAITING_HUMAN.value),
    (ExecutionState.RUNNING.value, 'OFFICIAL_REVIEW_STARTED'): (LifecycleState.UNDER_REVIEW.value, ExecutionState.WAITING_HUMAN.value),
    (ExecutionState.RUNNING.value, 'TRANSIENT_FAILURE'): (None, ExecutionState.RETRYING.value),
    (ExecutionState.RUNNING.value, 'PERMANENT_FAILURE'): (None, ExecutionState.BLOCKED.value),
    (ExecutionState.RETRYING.value, 'RETRY'): (None, ExecutionState.RUNNING.value),
    (ExecutionState.WAITING_EVENT.value, 'CORRECTION_RECEIVED'): (LifecycleState.EXTRACTION_PENDING.value, ExecutionState.RUNNING.value),
    (ExecutionState.WAITING_EVENT.value, 'OFFICIAL_REVIEW_STARTED'): (LifecycleState.UNDER_REVIEW.value, ExecutionState.WAITING_HUMAN.value),
    (ExecutionState.WAITING_EVENT.value, 'OFFICIAL_APPROVED'): (LifecycleState.ACCEPTED.value, ExecutionState.WAITING_TIMER.value),
    (ExecutionState.WAITING_EVENT.value, 'OFFICIAL_REQUESTED_CORRECTION'): (LifecycleState.CORRECTION_REQUIRED.value, ExecutionState.WAITING_EVENT.value),
    (ExecutionState.WAITING_TIMER.value, 'TIMER_FIRED'): (LifecycleState.ESCALATED.value, ExecutionState.RUNNING.value),
    (ExecutionState.WAITING_EVENT.value, 'TIMER_FIRED'): (LifecycleState.ESCALATED.value, ExecutionState.WAITING_HUMAN.value),
    (ExecutionState.WAITING_HUMAN.value, 'OFFICIAL_APPROVED'): (LifecycleState.ACCEPTED.value, ExecutionState.WAITING_TIMER.value),
    (ExecutionState.WAITING_HUMAN.value, 'OFFICIAL_REVIEW_STARTED'): (LifecycleState.UNDER_REVIEW.value, ExecutionState.WAITING_HUMAN.value),
    (ExecutionState.WAITING_HUMAN.value, 'OFFICIAL_REQUESTED_CORRECTION'): (LifecycleState.CORRECTION_REQUIRED.value, ExecutionState.WAITING_EVENT.value),
    (ExecutionState.WAITING_TIMER.value, 'RELEASE_REQUESTED'): (LifecycleState.AWAITING_RELEASE_DECISION.value, ExecutionState.WAITING_HUMAN.value),
    (ExecutionState.WAITING_TIMER.value, 'RENEWAL_REQUESTED'): (LifecycleState.RENEWAL_REQUIRED.value, ExecutionState.WAITING_EVENT.value),
    (ExecutionState.WAITING_HUMAN.value, 'RELEASE_APPROVED'): (LifecycleState.RELEASE_APPROVED.value, ExecutionState.COMPLETED.value),
    (ExecutionState.WAITING_HUMAN.value, 'RELEASE_REJECTED'): (LifecycleState.RELEASE_REJECTED.value, ExecutionState.WAITING_TIMER.value),
    (ExecutionState.RUNNING.value, 'PAUSE'): (None, ExecutionState.PAUSED.value),
    (ExecutionState.PAUSED.value, 'RESUME'): (None, ExecutionState.RETRYING.value),
    (ExecutionState.RUNNING.value, 'COMPLETE'): (LifecycleState.COMPLETED.value, ExecutionState.COMPLETED.value),
}


def transition(instance, event: str, *, actor_role: str = 'system') -> tuple[str | None, str]:
    key = (instance.execution_state, event)
    if key not in ALLOWED:
        raise InvalidStateTransition(f"Workflow cannot handle {event} while {instance.execution_state}.")
    if event in {'OFFICIAL_APPROVED','OFFICIAL_REQUESTED_CORRECTION','PAUSE','RESUME'} and actor_role not in {'aicte_official','admin'}:
        raise InvalidStateTransition('This workflow transition requires an authorized official.')
    lifecycle, execution = ALLOWED[key]
    return lifecycle, execution
