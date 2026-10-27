"""Opt-in synchronous workflow execution for local development."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import ExecutionState
from app.models.workflow import OutboxEvent, WorkflowInstance


async def run_inline_workflow_if_enabled(session: AsyncSession, fdr_id: int) -> bool:
    """Run a newly queued workflow inline when local eager mode is enabled."""
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
