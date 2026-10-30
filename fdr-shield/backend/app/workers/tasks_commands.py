"""Background execution for confirmed allowlisted Command Center plans."""
from .celery_app import celery_app, run_async_task
from app.core.database import SessionLocal
from app.models.workflow import CommandExecution
from app.services.command_service import execute


@celery_app.task(name='app.workers.tasks_commands.process_command',acks_late=True)
def process_command(command_id: int):
    return run_async_task(_run(command_id))


async def _run(command_id: int):
    async with SessionLocal() as session:
        await execute(session,command_id)
        await session.commit()
        command=await session.get(CommandExecution,command_id)
        return {'command_id':command_id,'status':command.status if command else 'missing'}
