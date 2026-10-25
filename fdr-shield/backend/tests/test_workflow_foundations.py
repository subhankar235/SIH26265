import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.audit_log import AuditLog
from app.models import FDR, Institution
from app.models.notification import Notification
from app.models.workflow import NotificationDeliveryAttempt, OutboxEvent, WorkflowEvent
from app.services import outbox_service
from app.services.outbox_service import enqueue
from app.services.workflow_events import publish


def test_event_and_outbox_enqueue_are_deduplicated():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            assert await publish(session, 1, 'FDR_SUBMITTED', {'fdr_id': 10}, 'event:fdr:10:submitted')
            assert not await publish(session, 1, 'FDR_SUBMITTED', {'fdr_id': 10}, 'event:fdr:10:submitted')
            assert await enqueue(session, '1', 'WORKFLOW_WAKE', {'workflow_instance_id': 1}, 'wake:1:v1')
            assert not await enqueue(session, '1', 'WORKFLOW_WAKE', {'workflow_instance_id': 1}, 'wake:1:v1')
            await session.commit()
            assert await session.scalar(select(WorkflowEvent.id).where(WorkflowEvent.dedupe_key == 'event:fdr:10:submitted'))
            assert await session.scalar(select(OutboxEvent.id).where(OutboxEvent.idempotency_key == 'wake:1:v1'))
        await engine.dispose()
    asyncio.run(run())


def test_audit_log_orm_mutation_is_rejected():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            row = AuditLog(user_id=None, entity='fdr', entity_id=1, action='created', ip_address='system',
                delta_changes={}, created_at=datetime.now(timezone.utc).replace(tzinfo=None))
            session.add(row); await session.commit()
            row.action = 'tampered'
            with pytest.raises(RuntimeError, match='append-only'):
                await session.flush()
            await session.rollback()
        await engine.dispose()
    asyncio.run(run())


def test_outbox_email_is_claimed_once_and_expired_inflight_is_not_resent(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        deliveries = []
        async def fake_send(payload): deliveries.append(payload['notification_id']); return True
        monkeypatch.setattr(outbox_service, '_send_notification', fake_send)
        async with factory() as session:
            institution = Institution(aicte_id='AICTE-OUTBOX-001', name='Outbox College', state='Delhi',
                head_name='Principal', contact_email='outbox@example.test', contact_phone='9000000004', status='active')
            session.add(institution); await session.flush()
            fdr = FDR(institution_id=institution.id, fdr_number='OUTBOX-001', bank_name='SBI', branch='Main',
                amount=500000, issue_date=datetime.now(timezone.utc).date(),
                maturity_date=datetime.now(timezone.utc).date()+timedelta(days=30), status='submitted',
                trust_badge='self_declared', declared_data={})
            session.add(fdr); await session.flush()
            note = Notification(fdr_id=fdr.id, stage='T-30', channel='email', recipient=institution.contact_email, status='queued')
            session.add(note); await session.flush()
            payload={'notification_id':note.id,'channel':'email','recipient':note.recipient,'subject':'Test','body':'Hello'}
            await enqueue(session, str(fdr.id), 'DELIVER_NOTIFICATION', payload, 'notification:1:T30:email')
            await session.commit()
            result = await outbox_service.dispatch_batch(session)
            await session.commit()
            assert result['sent'] == 1 and deliveries == [note.id]
            assert (await session.get(Notification, note.id)).status == 'sent'
            assert (await session.scalar(select(NotificationDeliveryAttempt).where(
                NotificationDeliveryAttempt.notification_id == note.id))).status == 'sent'

            uncertain_note = Notification(fdr_id=fdr.id, stage='T-0', channel='email', recipient=note.recipient, status='queued')
            session.add(uncertain_note); await session.flush()
            now = datetime.now(timezone.utc)
            uncertain_outbox = OutboxEvent(aggregate_id=str(fdr.id),event_type='DELIVER_NOTIFICATION',
                payload={**payload,'notification_id':uncertain_note.id},idempotency_key='notification:1:T0:email',
                status='processing',attempts=1,next_attempt_at=now-timedelta(minutes=5),
                locked_until=now-timedelta(seconds=1))
            session.add(uncertain_outbox); await session.flush()
            session.add(NotificationDeliveryAttempt(notification_id=uncertain_note.id,attempt_no=1,
                idempotency_key='notification:1:T0:email:attempt:1',provider='email',status='sending',scheduled_at=now))
            await session.commit()
            result = await outbox_service.dispatch_batch(session)
            await session.commit()
            assert result['dead'] == 1
            assert deliveries == [note.id]  # ambiguous send is not automatically repeated
            assert (await session.get(Notification, uncertain_note.id)).status == 'failed'
        await engine.dispose()
    asyncio.run(run())
