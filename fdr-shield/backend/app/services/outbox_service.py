"""Transactional outbox enqueue and at-least-once dispatcher.

Notification sends enter PROCESSING with a committed lease/attempt before calling
the provider. If a process dies inside the send window, the expired lease becomes
DEAD/UNCERTAIN rather than being resent blindly (SMTP has no idempotency API).
Workflow wake messages are safe to republish because the workflow claim is locked
and every node attempt is recorded transactionally.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification
from app.models.workflow import NotificationDeliveryAttempt, OutboxEvent

MAX_ATTEMPTS = 8
DELIVERY_LEASE_SECONDS = 180


def now_utc(): return datetime.now(timezone.utc)
def _aware(value): return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


async def enqueue(session: AsyncSession, aggregate_id: str, event_type: str,
                  payload: dict, idempotency_key: str, *, not_before: datetime | None = None) -> bool:
    """Insert an outbox row in the same DB transaction as its business mutation."""
    table = OutboxEvent.__table__
    values = {'aggregate_id': str(aggregate_id), 'event_type': event_type,
              'payload': payload or {}, 'idempotency_key': idempotency_key,
              'status': 'pending', 'attempts': 0, 'next_attempt_at': not_before or now_utc()}
    dialect = session.get_bind().dialect.name
    if dialect == 'postgresql':
        stmt = pg_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=['idempotency_key']).returning(table.c.id)
    elif dialect == 'sqlite':
        stmt = sqlite_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=['idempotency_key']).returning(table.c.id)
    else:
        found = await session.scalar(select(OutboxEvent.id).where(OutboxEvent.idempotency_key == idempotency_key))
        if found: return False
        session.add(OutboxEvent(**values)); await session.flush(); return True
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _send_notification(payload: dict) -> bool:
    channel = payload['channel']
    recipient = payload['recipient']
    subject = payload['subject']
    body = payload['body']
    if channel == 'email':
        from app.integrations.email_client import send_email
        return await send_email(recipient, subject, body)
    if channel == 'telegram':
        from app.integrations.telegram_client import send_message
        return await send_message(recipient, subject + '\n' + body)
    if channel == 'whatsapp_mock':
        from app.integrations.whatsapp_mock import send_whatsapp
        return await send_whatsapp(recipient, subject + '\n' + body)
    raise ValueError(f'Unsupported notification channel: {channel}')


async def dispatch_batch(session: AsyncSession, limit: int = 1) -> dict:
    """Claim due effects using SKIP LOCKED; deliver notifications through a lease."""
    now = now_utc()
    query = (select(OutboxEvent).where(
        ((OutboxEvent.status.in_(['pending','failed'])) & (OutboxEvent.next_attempt_at <= now)) |
        ((OutboxEvent.status == 'processing') & (OutboxEvent.locked_until <= now))
    ).order_by(OutboxEvent.id).limit(limit).with_for_update(skip_locked=True))
    # This invocation owns at most one lease because the notification provider
    # boundary commits before sending; committing releases every selected row lock.
    # Batch parallelism belongs in multiple dispatcher processes, not in one transaction.
    rows = list((await session.scalars(query.limit(1))).all())
    queued = sent = retried = dead = 0
    for row in rows:
        if row.status == 'processing':
            # Provider result is ambiguous after lease expiry; never duplicate-send blindly.
            attempt = await session.scalar(select(NotificationDeliveryAttempt).where(
                NotificationDeliveryAttempt.notification_id == int(row.payload['notification_id']),
                NotificationDeliveryAttempt.status == 'sending').order_by(NotificationDeliveryAttempt.attempt_no.desc()))
            if attempt and attempt.status == 'sending':
                attempt.status = 'uncertain'
                attempt.error = 'Dispatcher lease expired during provider call; delivery outcome is uncertain; manual review required.'
                notification = await session.get(Notification, int(row.payload['notification_id']))
                if notification: notification.status = 'failed'
            row.status = 'dead'; row.last_error = 'Delivery result uncertain after dispatcher crash; not resent.'
            row.locked_until = None; dead += 1
            continue

        if row.event_type in {'WORKFLOW_WAKE','COMMAND_EXECUTE'}:
            try:
                if row.event_type == 'WORKFLOW_WAKE':
                    from app.workers.tasks_workflow import process_workflow
                    process_workflow.apply_async(args=[int(row.payload['workflow_instance_id'])],
                        task_id=f'outbox-{row.id}', headers={'outbox_id': row.id,
                            'idempotency_key': row.idempotency_key})
                else:
                    from app.workers.tasks_workflow import process_command
                    process_command.apply_async(args=[int(row.payload['command_id'])],
                        task_id=f'outbox-{row.id}', headers={'outbox_id': row.id,
                            'idempotency_key': row.idempotency_key})
                row.status = 'sent'; row.sent_at = now; row.last_error = None
                row.attempts += 1; queued += 1
            except Exception as exc:
                row.attempts += 1; row.last_error = f'{type(exc).__name__}: {exc}'[:2000]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = 'dead'; dead += 1
                else:
                    row.status = 'pending'
                    row.next_attempt_at = now + timedelta(seconds=min(2 ** row.attempts, 900)); retried += 1
            continue

        if row.event_type != 'DELIVER_NOTIFICATION':
            row.attempts += 1; row.status = 'dead'
            row.last_error = f'Unsupported outbox event type: {row.event_type}'
            dead += 1
            continue

        notification = await session.get(Notification, int(row.payload['notification_id']))
        if not notification:
            row.status = 'dead'; row.last_error = 'Notification intent is missing.'; dead += 1
            continue
        previous = await session.scalar(select(NotificationDeliveryAttempt).where(
            NotificationDeliveryAttempt.notification_id == notification.id,
            NotificationDeliveryAttempt.status == 'sent'))
        if previous:
            notification.status = 'sent'; row.status = 'sent'; row.sent_at = previous.sent_at or now
            row.locked_until = None; sent += 1
            continue
        row.attempts += 1
        row.status = 'processing'
        row.locked_until = now + timedelta(seconds=DELIVERY_LEASE_SECONDS)
        previous_attempt_no=int(await session.scalar(select(func.max(NotificationDeliveryAttempt.attempt_no)).where(
            NotificationDeliveryAttempt.notification_id==notification.id)) or 0)
        delivery_attempt_no=previous_attempt_no+1
        attempt = NotificationDeliveryAttempt(notification_id=notification.id,
            attempt_no=delivery_attempt_no, idempotency_key=f'{row.idempotency_key}:attempt:{delivery_attempt_no}',
            provider=notification.channel, template_version=row.payload.get('template_version'),
            status='sending', scheduled_at=now)
        session.add(attempt)
        await session.commit()  # commit the send lease before crossing the provider boundary
        try:
            accepted = await _send_notification(row.payload)
            provider_error = None if accepted else 'Provider did not accept the notification.'
        except Exception as exc:
            accepted = False; provider_error = f'{type(exc).__name__}: {exc}'[:2000]
        row_id = row.id
        row = await session.scalar(select(OutboxEvent).where(OutboxEvent.id == row_id).with_for_update())
        attempt = await session.scalar(select(NotificationDeliveryAttempt).where(
            NotificationDeliveryAttempt.notification_id == int(row.payload['notification_id']),
            NotificationDeliveryAttempt.attempt_no == delivery_attempt_no))
        notification = await session.get(Notification, int(row.payload['notification_id']))
        if accepted:
            attempt.status = 'sent'; attempt.sent_at = now_utc()
            attempt.provider_response = {'accepted': True}
            notification.status = 'sent'; notification.sent_at = now_utc().replace(tzinfo=None)
            row.status = 'sent'; row.sent_at = now_utc(); row.locked_until = None; row.last_error = None
            sent += 1
        else:
            attempt.status = 'failed'; attempt.error = provider_error
            notification.status = 'failed'
            row.last_error = provider_error
            row.locked_until = None
            if row.attempts >= MAX_ATTEMPTS:
                row.status = 'dead'; dead += 1
            else:
                row.status = 'pending'
                row.next_attempt_at = now_utc() + timedelta(seconds=min(2 ** row.attempts, 900)); retried += 1
    await session.flush()
    return {'claimed': len(rows), 'queued': queued, 'sent': sent, 'retried': retried, 'dead': dead}
