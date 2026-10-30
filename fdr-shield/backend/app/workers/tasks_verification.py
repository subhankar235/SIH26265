"""Deprecated task name retained as a compatibility shim to durable workflows."""
from .celery_app import celery_app, run_async_task
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.fdr import FDR
from app.models.workflow import WorkflowInstance
from app.services.outbox_service import enqueue
from app.core.exceptions import NotFound


@celery_app.task(name='app.workers.tasks_verification.run_verification_pipeline')
def run_verification_pipeline(fdr_id: int) -> None:
    """Old producers now wake the persistent workflow rather than running OCR inline."""
    run_async_task(_queue_workflow(fdr_id))


async def _queue_workflow(fdr_id: int) -> None:
    async with SessionLocal() as session:
        fdr = await session.get(FDR, fdr_id)
        if not fdr: raise NotFound('FDR not found')
        workflow = await session.scalar(select(WorkflowInstance).where(
            WorkflowInstance.fdr_id == fdr_id).order_by(WorkflowInstance.execution_version.desc()).limit(1))
        if not workflow: raise NotFound('FDR workflow has not been initialized')
        await enqueue(session, str(workflow.id), 'WORKFLOW_WAKE',
            {'workflow_instance_id': workflow.id, 'compatibility_trigger': True},
            f'workflow:{workflow.id}:compat-trigger:{workflow.version}')
        await session.commit()
