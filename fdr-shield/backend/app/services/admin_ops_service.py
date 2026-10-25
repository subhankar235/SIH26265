"""Phase 11 — Admin Operations Agent (Agent C) & Monitoring Service.

Provides:
- 11.1: Metrics collector: failed jobs, retries, dead letters, queue age,
       workflow duration per node, notification failure rate, stuck cases (> SLA).
- 11.2: Deterministic threshold rules: failure rate > X%, expired leases, dead letters > 0.
- 11.3: Agent tools:
       get_failed_jobs, get_stuck_cases, get_delivery_failures,
       generate_health_report, recommend_recovery;
       safe actions limited to requeue failed job / send test alert with confirmation.
- 11.4: Strictly forbidden: change permissions, security settings, delete data.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ExecutionState, Role
from app.core.exceptions import InvalidStateTransition, NotFound, PermissionDenied
from app.models.notification import Notification
from app.models.user import User
from app.models.workflow import (
    NotificationDeliveryAttempt,
    OutboxEvent,
    WorkflowInstance,
    WorkflowNodeExecution,
)
from app.services.audit_service import record

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 11.1: Metrics Collector (Database Queries)
# ---------------------------------------------------------------------------

async def collect_operations_metrics(session: AsyncSession) -> dict:
    """Collect real-time system metrics across workflow, outbox, and notifications."""
    now = datetime.now(timezone.utc)

    # 1. Failed jobs count
    failed_nodes_count = await session.scalar(
        select(func.count(WorkflowNodeExecution.id)).where(WorkflowNodeExecution.status == 'failed')
    ) or 0
    dead_outbox_count = await session.scalar(
        select(func.count(OutboxEvent.id)).where(OutboxEvent.status == 'dead')
    ) or 0
    failed_jobs_total = failed_nodes_count + dead_outbox_count

    # 2. Retries count
    retries_count = await session.scalar(
        select(func.count(WorkflowNodeExecution.id)).where(WorkflowNodeExecution.attempt > 1)
    ) or 0

    # 3. Dead letters count
    dead_letters = dead_outbox_count

    # 4. Oldest queue age (seconds)
    oldest_pending_outbox = await session.scalar(
        select(OutboxEvent.created_at).where(OutboxEvent.status.in_(['pending', 'processing']))
        .order_by(OutboxEvent.created_at.asc()).limit(1)
    )
    queue_age_seconds = 0.0
    if oldest_pending_outbox:
        dt = oldest_pending_outbox.replace(tzinfo=timezone.utc) if oldest_pending_outbox.tzinfo is None else oldest_pending_outbox
        queue_age_seconds = max(0.0, (now - dt).total_seconds())

    # 5. Workflow duration per node (avg and max ms)
    durations_query = (
        select(
            WorkflowNodeExecution.node_key,
            func.avg(WorkflowNodeExecution.duration_ms).label('avg_ms'),
            func.max(WorkflowNodeExecution.duration_ms).label('max_ms'),
            func.count(WorkflowNodeExecution.id).label('exec_count')
        )
        .where(WorkflowNodeExecution.duration_ms.is_not(None))
        .group_by(WorkflowNodeExecution.node_key)
    )
    duration_rows = (await session.execute(durations_query)).all()
    duration_per_node = {
        row.node_key: {
            'avg_ms': round(float(row.avg_ms), 1),
            'max_ms': int(row.max_ms),
            'count': int(row.exec_count)
        }
        for row in duration_rows
    }

    # 6. Notification failure rate
    total_notifications = await session.scalar(select(func.count(NotificationDeliveryAttempt.id))) or 0
    failed_notifications = await session.scalar(
        select(func.count(NotificationDeliveryAttempt.id)).where(
            NotificationDeliveryAttempt.status.in_(['failed', 'uncertain'])
        )
    ) or 0
    notification_failure_rate = (
        round((failed_notifications / total_notifications) * 100, 2)
        if total_notifications > 0 else 0.0
    )

    # 7. Stuck cases (RUNNING with expired worker lease or no progress > SLA of 2 hours)
    sla_cutoff = now - timedelta(hours=2)
    stuck_cases_count = await session.scalar(
        select(func.count(WorkflowInstance.id)).where(
            WorkflowInstance.execution_state.in_([ExecutionState.RUNNING.value, ExecutionState.RETRYING.value]),
            (
                (WorkflowInstance.worker_lease_until.is_not(None) & (WorkflowInstance.worker_lease_until <= now)) |
                (WorkflowInstance.updated_at <= sla_cutoff)
            )
        )
    ) or 0

    return {
        'timestamp': now.isoformat(),
        'failed_jobs': failed_jobs_total,
        'failed_nodes': failed_nodes_count,
        'dead_letters': dead_letters,
        'retries': retries_count,
        'queue_age_seconds': round(queue_age_seconds, 1),
        'duration_per_node': duration_per_node,
        'notification_failure_rate_percent': notification_failure_rate,
        'notifications_total': total_notifications,
        'notifications_failed': failed_notifications,
        'stuck_cases': stuck_cases_count,
    }


# ---------------------------------------------------------------------------
# Step 11.2: Deterministic Threshold Rules
# ---------------------------------------------------------------------------

def evaluate_threshold_rules(metrics: dict) -> dict:
    """Evaluate deterministic threshold rules:
    - Failure rate > 10%
    - Instance in RUNNING with expired lease / stuck cases > 0
    - Outbox DEAD count > 0
    - Oldest queue age > 300s (5 minutes)
    """
    breaches = []

    # Rule 1: Dead letters (CRITICAL)
    if metrics['dead_letters'] > 0:
        breaches.append({
            'rule': 'DEAD_LETTERS_EXISTS',
            'severity': 'critical',
            'message': f"Transactional outbox has {metrics['dead_letters']} dead letter event(s) requiring review/requeue.",
            'current_value': metrics['dead_letters'],
            'threshold': 0,
        })

    # Rule 2: Stuck cases with expired worker lease (CRITICAL)
    if metrics['stuck_cases'] > 0:
        breaches.append({
            'rule': 'STUCK_CASES_EXPIRED_LEASE',
            'severity': 'critical',
            'message': f"{metrics['stuck_cases']} workflow instance(s) are stuck past SLA or have expired leases.",
            'current_value': metrics['stuck_cases'],
            'threshold': 0,
        })

    # Rule 3: Notification delivery failure rate > 10% (WARNING / CRITICAL)
    rate = metrics['notification_failure_rate_percent']
    if rate > 15.0:
        breaches.append({
            'rule': 'NOTIFICATION_FAILURE_RATE_HIGH',
            'severity': 'critical',
            'message': f"Notification delivery failure rate is {rate}%, exceeding critical threshold of 15%.",
            'current_value': f"{rate}%",
            'threshold': '15%',
        })
    elif rate > 10.0:
        breaches.append({
            'rule': 'NOTIFICATION_FAILURE_RATE_ELEVATED',
            'severity': 'warning',
            'message': f"Notification delivery failure rate is {rate}%, exceeding warning threshold of 10%.",
            'current_value': f"{rate}%",
            'threshold': '10%',
        })

    # Rule 4: Queue age (WARNING)
    q_age = metrics['queue_age_seconds']
    if q_age > 300:
        breaches.append({
            'rule': 'QUEUE_AGE_ELEVATED',
            'severity': 'warning',
            'message': f"Outbox queue latency is high: oldest message has been pending for {int(q_age)} seconds.",
            'current_value': f"{int(q_age)}s",
            'threshold': '300s',
        })

    # Health status determination
    if any(b['severity'] == 'critical' for b in breaches):
        health_status = 'CRITICAL'
    elif breaches:
        health_status = 'DEGRADED'
    else:
        health_status = 'HEALTHY'

    return {
        'status': health_status,
        'healthy': health_status == 'HEALTHY',
        'breach_count': len(breaches),
        'breaches': breaches,
        'metrics': metrics,
    }


# ---------------------------------------------------------------------------
# Step 11.3: Agent Tools (Read-only + Safe Actions with Confirmation)
# ---------------------------------------------------------------------------

async def get_failed_jobs(session: AsyncSession, limit: int = 50) -> dict:
    """Tool 1: get_failed_jobs."""
    failed_nodes = list((await session.scalars(
        select(WorkflowNodeExecution).where(WorkflowNodeExecution.status == 'failed')
        .order_by(WorkflowNodeExecution.id.desc()).limit(limit)
    )).all())

    dead_outbox = list((await session.scalars(
        select(OutboxEvent).where(OutboxEvent.status == 'dead')
        .order_by(OutboxEvent.id.desc()).limit(limit)
    )).all())

    return {
        'failed_node_executions': [
            {
                'id': n.id,
                'workflow_instance_id': n.workflow_instance_id,
                'node_key': n.node_key,
                'attempt': n.attempt,
                'error_class': n.error_class,
                'error_code': n.error_code,
                'error_message': n.error_message,
                'finished_at': n.finished_at.isoformat() if n.finished_at else None,
            }
            for n in failed_nodes
        ],
        'dead_outbox_events': [
            {
                'id': o.id,
                'aggregate_id': o.aggregate_id,
                'event_type': o.event_type,
                'attempts': o.attempts,
                'last_error': o.last_error,
                'created_at': o.created_at.isoformat() if o.created_at else None,
            }
            for o in dead_outbox
        ]
    }


async def get_stuck_cases(session: AsyncSession) -> dict:
    """Tool 2: get_stuck_cases."""
    now = datetime.now(timezone.utc)
    sla_cutoff = now - timedelta(hours=2)
    query = (
        select(WorkflowInstance).where(
            WorkflowInstance.execution_state.in_([ExecutionState.RUNNING.value, ExecutionState.RETRYING.value]),
            (
                (WorkflowInstance.worker_lease_until.is_not(None) & (WorkflowInstance.worker_lease_until <= now)) |
                (WorkflowInstance.updated_at <= sla_cutoff)
            )
        ).limit(50)
    )
    rows = list((await session.scalars(query)).all())
    return {
        'stuck_count': len(rows),
        'cases': [
            {
                'workflow_id': w.id,
                'fdr_id': w.fdr_id,
                'institution_id': w.institution_id,
                'execution_state': w.execution_state,
                'current_node': w.current_node,
                'worker_lease_until': w.worker_lease_until.isoformat() if w.worker_lease_until else None,
                'lease_expired': bool(w.worker_lease_until and w.worker_lease_until <= now),
                'updated_at': w.updated_at.isoformat() if w.updated_at else None,
            }
            for w in rows
        ]
    }


async def get_delivery_failures(session: AsyncSession, hours: int = 24) -> dict:
    """Tool 3: get_delivery_failures."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = (
        select(NotificationDeliveryAttempt).where(
            NotificationDeliveryAttempt.status.in_(['failed', 'uncertain']),
            NotificationDeliveryAttempt.scheduled_at >= cutoff
        ).order_by(NotificationDeliveryAttempt.scheduled_at.desc()).limit(100)
    )
    rows = list((await session.scalars(query)).all())
    by_channel = {}
    for r in rows:
        ch = r.provider
        by_channel[ch] = by_channel.get(ch, 0) + 1

    return {
        'total_failures': len(rows),
        'by_channel': by_channel,
        'recent_failures': [
            {
                'id': r.id,
                'notification_id': r.notification_id,
                'channel': r.provider,
                'status': r.status,
                'attempt_no': r.attempt_no,
                'error': r.error,
                'scheduled_at': r.scheduled_at.isoformat() if r.scheduled_at else None,
            }
            for r in rows[:20]
        ]
    }


async def generate_health_report(session: AsyncSession) -> dict:
    """Tool 4: generate_health_report."""
    metrics = await collect_operations_metrics(session)
    report = evaluate_threshold_rules(metrics)
    return report


async def recommend_recovery(session: AsyncSession) -> dict:
    """Tool 5: recommend_recovery."""
    report = await generate_health_report(session)
    recommendations = []

    for b in report['breaches']:
        rule = b['rule']
        if rule == 'DEAD_LETTERS_EXISTS':
            recommendations.append({
                'action': 'requeue_failed_job',
                'description': 'Inspect error in dead letters and requeue transient outbox events.',
                'safe': True,
                'requires_confirmation': True,
            })
        elif rule == 'STUCK_CASES_EXPIRED_LEASE':
            recommendations.append({
                'action': 'manual_review',
                'description': 'Inspect the stuck workflow and use the existing workflow recovery controls after review.',
                'safe': False,
                'requires_confirmation': False,
            })
        elif rule in {'NOTIFICATION_FAILURE_RATE_HIGH', 'NOTIFICATION_FAILURE_RATE_ELEVATED'}:
            recommendations.append({
                'action': 'send_test_alert',
                'description': 'Send diagnostic test alert to verify notification provider connectivity.',
                'safe': True,
                'requires_confirmation': True,
            })
        elif rule == 'QUEUE_AGE_ELEVATED':
            recommendations.append({
                'action': 'inspect_dispatchers',
                'description': 'Verify worker dispatchers are active and polling the transactional outbox.',
                'safe': False,
                'requires_confirmation': False,
            })

    if not recommendations:
        recommendations.append({
            'action': 'none',
            'description': 'All system metrics are within normal operational thresholds. No recovery actions needed.',
            'safe': True,
            'requires_confirmation': False,
        })

    return {
        'health_status': report['status'],
        'recommendations': recommendations
    }


# ---------------------------------------------------------------------------
# Safe Actions (Gated by Confirmation)
# ---------------------------------------------------------------------------

async def requeue_failed_job(session: AsyncSession, actor: User, outbox_id: int, confirmed: bool) -> dict:
    """Safe Action 1: Requeue a failed outbox job. Confirmation mandatory."""
    event = await session.get(OutboxEvent, outbox_id)
    if not event:
        raise NotFound(f'Outbox event #{outbox_id} not found.')

    if event.status != 'dead':
        raise InvalidStateTransition('Only dead-letter outbox events may be requeued.')

    if not confirmed:
        return {
            'action': 'requeue_failed_job',
            'outbox_id': outbox_id,
            'event_type': event.event_type,
            'current_status': event.status,
            'requires_confirmation': True,
            'effect_summary': f"Reset outbox event #{outbox_id} ({event.event_type}) from '{event.status}' to 'pending' with 0 attempts.",
        }

    previous_status = event.status
    event.status = 'pending'
    event.attempts = 0
    event.locked_until = None
    event.last_error = None
    event.next_attempt_at = datetime.now(timezone.utc)
    await session.flush()

    await record(
        session, actor.id, 'outbox_event', event.id, 'ADMIN_REQUEUED_JOB', '',
        {'status': [previous_status, 'pending']}, actor_type='admin'
    )
    return {
        'action': 'requeue_failed_job',
        'outbox_id': outbox_id,
        'status': 'pending',
        'message': f"Outbox event #{outbox_id} successfully requeued."
    }


async def send_test_alert(session: AsyncSession, actor: User, channel: str, recipient: str, confirmed: bool) -> dict:
    """Safe Action 2: Send test alert to check provider. Confirmation mandatory."""
    if not confirmed:
        return {
            'action': 'send_test_alert',
            'channel': channel,
            'recipient': recipient,
            'requires_confirmation': True,
            'effect_summary': f"Send diagnostic test notification to {recipient} via {channel}.",
        }

    from app.services.outbox_service import enqueue as enqueue_outbox
    notif = Notification(
        fdr_id=None,
        institution_id=None,
        type='test_diagnostic_alert',
        channel=channel,
        recipient=recipient,
        subject='AICTE FDR Portal Diagnostic Alert',
        body=f'This is an automated operational diagnostic alert triggered by Admin {actor.email}.',
        status='pending'
    )
    session.add(notif)
    await session.flush()
    await enqueue_outbox(
        session, f'test-notification:{notif.id}', 'DELIVER_NOTIFICATION',
        {'notification_id': notif.id, 'channel': channel, 'recipient': recipient,
         'subject': notif.subject, 'body': notif.body, 'template_version': 'admin-test-v1'},
        f'admin-test-notification:{notif.id}',
    )

    await record(
        session, actor.id, 'notification', notif.id, 'ADMIN_TEST_ALERT_SENT', '',
        {'channel': [None, channel], 'recipient': [None, recipient]}, actor_type='admin'
    )
    return {
        'action': 'send_test_alert',
        'notification_id': notif.id,
        'channel': channel,
        'status': 'queued',
        'message': f"Test notification #{notif.id} queued for delivery via {channel}."
    }


# ---------------------------------------------------------------------------
# Step 11.4: Forbidden Operations Guard
# ---------------------------------------------------------------------------

FORBIDDEN_PATTERNS = [
    re.compile(r'\b(change|modify|grant|revoke|elevate)\b.*\b(role|permission|privilege|admin)\b', re.I),
    re.compile(r'\b(delete|drop|truncate|purge|destroy)\b.*\b(data|table|audit|fdr|user|record)\b', re.I),
    re.compile(r'\b(security|jwt|cors|cookie|mfa|secret|cipher)\b.*\b(config|disable|change|modify)\b', re.I),
    re.compile(r'\bdrop\s+table\b', re.I),
    re.compile(r'\bdelete\s+from\b', re.I),
]


def check_forbidden_operation(text: str) -> None:
    """Enforces Step 11.4: strictly forbid permission changes, security setting modifications, and data deletion."""
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            raise PermissionDenied(
                'Action is prohibited by system security policy: Agent C cannot change permissions, '
                'modify security settings, or delete database/audit records.'
            )


# ---------------------------------------------------------------------------
# Admin Ops Agent (Agent C) Natural-Language Interface
# ---------------------------------------------------------------------------

async def process_admin_ops_command(session: AsyncSession, actor: User, text: str, confirm_action: bool = False, action_args: Optional[dict] = None) -> dict:
    """Process Admin Operations Agent instructions."""
    if actor.role != Role.ADMIN.value:
        raise PermissionDenied('Admin Operations Agent is strictly reserved for the Administrator role.')

    # Step 11.4 Security Check
    check_forbidden_operation(text)

    low = text.casefold()

    if 'requeue' in low:
        # Requeue job
        m = re.search(r'#?(\d+)', text)
        outbox_id = int(m.group(1)) if m else (action_args or {}).get('outbox_id')
        if not outbox_id:
            raise InvalidStateTransition('Specify the outbox event ID to requeue (e.g. "Requeue failed job #12").')
        return await requeue_failed_job(session, actor, outbox_id, confirmed=confirm_action)

    elif 'test alert' in low or 'send alert' in low or 'test notification' in low:
        channel = (action_args or {}).get('channel', 'email')
        recipient = (action_args or {}).get('recipient', actor.email)
        return await send_test_alert(session, actor, channel, recipient, confirmed=confirm_action)

    elif 'failed' in low or 'dead letter' in low or 'error' in low:
        data = await get_failed_jobs(session)
        fn_count = len(data['failed_node_executions'])
        dl_count = len(data['dead_outbox_events'])
        return {
            'reply': f"Found {fn_count} failed workflow execution(s) and {dl_count} dead letter outbox event(s).",
            'data': data
        }

    elif 'stuck' in low or 'lease' in low:
        data = await get_stuck_cases(session)
        count = data['stuck_count']
        return {
            'reply': f"There are {count} workflow cases currently stuck past SLA or with expired leases.",
            'data': data
        }

    elif 'delivery' in low or 'notification' in low:
        data = await get_delivery_failures(session)
        return {
            'reply': f"Recorded {data['total_failures']} notification delivery failures in the past 24 hours.",
            'data': data
        }

    elif 'recommend' in low or 'recover' in low:
        data = await recommend_recovery(session)
        return {
            'reply': f"System health is {data['health_status']}. Generated {len(data['recommendations'])} recovery recommendations.",
            'data': data
        }

    else:
        # Default: Health report
        data = await generate_health_report(session)
        return {
            'reply': f"Overall system health status is {data['status']} with {data['breach_count']} threshold breach(es).",
            'data': data
        }
