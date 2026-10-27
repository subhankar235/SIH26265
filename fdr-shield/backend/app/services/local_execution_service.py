"""Opt-in synchronous workflow execution for local development."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import ExecutionState
from app.models.workflow import CommandExecution, OutboxEvent, WorkflowInstance


async def run_inline_workflow_if_enabled(
    session: AsyncSession, fdr_id: int, *, resume_active: bool = False
) -> bool:
    """Run a workflow inline when local eager mode is enabled."""
    if not get_settings().celery_task_always_eager:
        return False

    instance = await session.scalar(
        select(WorkflowInstance)
        .where(WorkflowInstance.fdr_id == fdr_id)
        .order_by(WorkflowInstance.execution_version.desc())
        .limit(1)
    )
    if not instance or instance.execution_state not in {
        ExecutionState.NOT_STARTED.value,
        ExecutionState.RUNNING.value,
        ExecutionState.RETRYING.value,
    }:
        return False
    if resume_active and instance.execution_state in {
        ExecutionState.RUNNING.value,
        ExecutionState.RETRYING.value,
    }:
        # Local inline recovery is an explicit takeover; do not run a worker alongside it.
        instance.worker_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)

    wake_ids = list(
        (
            await session.scalars(
                select(OutboxEvent.id).where(
                    OutboxEvent.aggregate_id == str(instance.id),
                    OutboxEvent.event_type == "WORKFLOW_WAKE",
                    OutboxEvent.status == "pending",
                )
            )
        ).all()
    )
    # Persist the upload and its outbox event before the workflow reads the scan.
    await session.commit()

    from app.workers.tasks_workflow import _process_workflow
    from app.workflows.definition import NODES

    for _ in range(len(NODES) + 1):
        await _process_workflow(instance.id)
        await session.refresh(instance)
        if instance.execution_state not in {
            ExecutionState.NOT_STARTED.value,
            ExecutionState.RUNNING.value,
        }:
            break
    else:
        raise RuntimeError(f"Inline workflow {instance.id} exceeded its node limit")

    handled_wakes = list(
        (
            await session.scalars(
                select(OutboxEvent).where(OutboxEvent.id.in_(wake_ids))
            )
        ).all()
    )
    handled_at = datetime.now(timezone.utc)
    for event in handled_wakes:
        event.status = "sent"
        event.sent_at = handled_at
        event.last_error = None
    await session.commit()
    return True


async def run_inline_command_if_enabled(session: AsyncSession, command_id: int) -> bool:
    """Execute queued Command Center jobs inline in eager/local mode without a worker."""
    if not get_settings().celery_task_always_eager:
        return False
    command=await session.get(CommandExecution,command_id)
    if not command or command.status not in {'confirmed','running'}:
        return False
    command_wakes=list((await session.scalars(select(OutboxEvent).where(
        OutboxEvent.aggregate_id==str(command_id),OutboxEvent.event_type=='COMMAND_EXECUTE',
        OutboxEvent.status=='pending'))).all())
    prior_workflow_wakes=set((await session.scalars(select(OutboxEvent.id).where(
        OutboxEvent.event_type=='WORKFLOW_WAKE',OutboxEvent.status=='pending'))).all())
    await session.commit()

    from app.services.command_service import execute
    await execute(session,command_id)
    await session.commit()
    await session.refresh(command)

    # Commands such as document recheck enqueue workflow wakeups. Local eager mode
    # owns those follow-up steps too, so they do not remain queued for absent workers.
    workflow_wakes=list((await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type=='WORKFLOW_WAKE',OutboxEvent.status=='pending',
        OutboxEvent.id.not_in(prior_workflow_wakes or {-1})))).all())
    workflow_ids={int(event.payload['workflow_instance_id']) for event in workflow_wakes
        if event.payload and event.payload.get('workflow_instance_id') is not None}
    pending_workflow_events=[]
    for workflow_id in workflow_ids:
        workflow=await session.get(WorkflowInstance,workflow_id)
        if workflow:
            if await run_inline_workflow_if_enabled(session,workflow.fdr_id,resume_active=True):
                pending_workflow_events.extend(event for event in workflow_wakes
                    if event.aggregate_id==str(workflow_id))

    completed_at=datetime.now(timezone.utc)
    for event in [*command_wakes,*pending_workflow_events]:
        event.status='sent';event.sent_at=completed_at;event.last_error=None
    await session.commit()
    return True
