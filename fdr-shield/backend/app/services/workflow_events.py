"""Idempotent workflow inbox/event and transactional outbox writers."""
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workflow import WorkflowEvent


async def publish(session: AsyncSession, instance_id: int, event_type: str,
                  payload: dict, dedupe_key: str) -> bool:
    """Insert one durable event. Returns False when its dedupe key already exists."""
    bind = session.get_bind()
    table = WorkflowEvent.__table__
    values = {'workflow_instance_id': instance_id, 'event_type': event_type,
              'payload': payload or {}, 'dedupe_key': dedupe_key}
    if bind.dialect.name == 'postgresql':
        stmt = pg_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=['dedupe_key']).returning(table.c.id)
    elif bind.dialect.name == 'sqlite':
        stmt = sqlite_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=['dedupe_key']).returning(table.c.id)
    else:
        exists = await session.scalar(__import__('sqlalchemy').select(WorkflowEvent.id)
            .where(WorkflowEvent.dedupe_key == dedupe_key))
        if exists: return False
        session.add(WorkflowEvent(**values)); await session.flush(); return True
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None
