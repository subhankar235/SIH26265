"""Celery application + beat schedule."""

from celery import Celery
from celery.schedules import crontab
import asyncio


from app.core.config import get_settings
settings=get_settings()
celery_app = Celery('fdr_shield',broker=settings.redis_url,backend=settings.redis_url,include=['app.workers.tasks_verification','app.workers.tasks_maturity','app.workers.tasks_workflow','app.workers.tasks_commands'])


celery_app.conf.task_always_eager=settings.celery_task_always_eager
celery_app.conf.task_eager_propagates=True
celery_app.conf.task_acks_late=True
celery_app.conf.task_reject_on_worker_lost=True
celery_app.conf.worker_prefetch_multiplier=1
def run_async_task(coroutine):
    """Run one async task and dispose pooled connections before its event loop closes."""
    from app.core.database import engine
    async def execute():
        try: return await coroutine
        finally: await engine.dispose()
    return asyncio.run(execute())
celery_app.conf.beat_schedule={
    'daily-maturity-scan':{'task':'app.workers.tasks_maturity.scan_maturities','schedule':crontab(hour=2,minute=0)},
    'dispatch-transactional-outbox':{'task':'app.workers.tasks_workflow.dispatch_outbox_task','schedule':10.0},
    'recover-expired-workflow-leases':{'task':'app.workers.tasks_workflow.recover_expired_leases','schedule':30.0},
}
