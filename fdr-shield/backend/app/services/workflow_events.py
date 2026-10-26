"""Idempotent workflow inbox/event and transactional outbox writers."""
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workflow import WorkflowEvent
from app.services.event_bus import get_event_bus


EXCEPTIONS_INBOX_EVENTS = {
    'exception.created', 'EXCEPTION_CLAIMED', 'EXCEPTION_RESOLVED',
    'OFFICIAL_ESCALATED_EXCEPTION', 'CORRECTION_SLA_EXPIRED'
}


async def publish(session: AsyncSession, instance_id: int, event_type: str,
                  payload: dict, dedupe_key: str) -> bool:
    """Insert one durable event. Returns False when its dedupe key already exists."""
    bind = session.get_bind()
    table = WorkflowEvent.__table__
    values = {'workflow_instance_id': instance_id, 'event_type': event_type,
              'payload': payload or {}, 'dedupe_key': dedupe_key}
    event_id = None
    if bind.dialect.name == 'postgresql':
        stmt = pg_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=['dedupe_key']).returning(table.c.id)
        result = await session.execute(stmt)
        event_id = result.scalar_one_or_none()
    elif bind.dialect.name == 'sqlite':
        stmt = sqlite_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=['dedupe_key']).returning(table.c.id)
        result = await session.execute(stmt)
        event_id = result.scalar_one_or_none()
    else:
        exists = await session.scalar(__import__('sqlalchemy').select(WorkflowEvent.id)
            .where(WorkflowEvent.dedupe_key == dedupe_key))
        if exists: return False
        evt = WorkflowEvent(**values)
        session.add(evt)
        await session.flush()
        event_id = evt.id

    if event_id is None:
        return False

    # Broadcast live event via event bus
    bus = get_event_bus()
    await bus.broadcast(f"workflow:{instance_id}", event_type, payload or {}, event_id=event_id)
    if event_type in EXCEPTIONS_INBOX_EVENTS:
        await bus.broadcast("inbox:exceptions", event_type, payload or {}, event_id=event_id)
    if event_type == 'approval.recorded':
        await bus.broadcast("inbox:approvals", event_type, payload or {}, event_id=event_id)

    return True
