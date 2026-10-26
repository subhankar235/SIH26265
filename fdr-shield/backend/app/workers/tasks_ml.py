"""Periodic raw metric capture for the BOCPD Gate 0 series."""
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.admin_ops_service import collect_operations_metrics
from app.services.ml_service import capture_operations_snapshot
from app.workers.celery_app import celery_app, run_async_task


@celery_app.task(name='app.workers.tasks_ml.capture_operations_snapshot')
def capture_operations_snapshot_task() -> dict:
    return run_async_task(_capture())


async def _capture() -> dict:
    async with SessionLocal() as session:
        metrics=await collect_operations_metrics(session)
        # Development/test metrics include demo-seeded activity and never qualify as
        # real training observations. Production snapshots are still raw measurements.
        synthetic=get_settings().app_env.lower() in {'dev','development','test'}
        row=await capture_operations_snapshot(session,metrics,is_synthetic=synthetic)
        await session.commit()
        return {'snapshot_id':row.id,'is_synthetic':synthetic,'captured_at':row.captured_at.isoformat()}
