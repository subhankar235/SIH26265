import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.enums import ExecutionState, LifecycleState
from app.core.exceptions import InvalidStateTransition
from app.models import FDR, Institution, User
from app.models.workflow import OutboxEvent, WorkflowInstance
from app.services.institution_assistant_service import (
    LIFECYCLE_NEXT_ACTIONS,
    derive_next_action,
    enforce_guardrails,
    get_case_state,
)
from app.services.admin_ops_service import (
    evaluate_threshold_rules,
    requeue_failed_job,
)
from app.services.admin_rules_service import append_version, create_rule, list_rules


def test_phase10_scoping_and_deterministic_actions():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
                                     connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            a = Institution(aicte_id='P10-A', name='A', state='Delhi', head_name='A',
                            contact_email='a@example.test', contact_phone='9000000011', status='active')
            b = Institution(aicte_id='P10-B', name='B', state='Delhi', head_name='B',
                            contact_email='b@example.test', contact_phone='9000000012', status='active')
            session.add_all([a, b]); await session.flush()
            fdr = FDR(institution_id=b.id, fdr_number='FDR-SECRET-991', bank_name='SBI', branch='', amount=10,
                      issue_date=date.today(), maturity_date=date.today() + timedelta(days=30),
                      status='submitted', trust_badge='self_declared', declared_data={})
            session.add(fdr); await session.flush()
            session.add(WorkflowInstance(fdr_id=fdr.id, institution_id=b.id, workflow_version='v1',
                execution_version=1, lifecycle_state=LifecycleState.ACCEPTED.value,
                execution_state=ExecutionState.NOT_STARTED.value, authorization_state='not_required'))
            await session.commit()
            assert (await get_case_state(session, a.id, 'FDR-SECRET-991'))['found'] is False
            own = await get_case_state(session, b.id, 'FDR-SECRET-991')
            assert own['next_action'] == derive_next_action('accepted')
            assert own['next_action'] == 'FDR verified and active in AICTE trust matrix. Monitor maturity date.'
        await engine.dispose()
    asyncio.run(run())


def test_phase10_guardrails_and_phase11_thresholds():
    assert all(derive_next_action(state) == action for state, action in LIFECYCLE_NEXT_ACTIONS.items())
    assert 'genuine' not in enforce_guardrails('This FDR is genuine').lower()
    assert 'unusual pattern — review suggested' in enforce_guardrails('fraud detected')
    metrics = {'dead_letters': 1, 'stuck_cases': 0, 'notification_failure_rate_percent': 0,
               'queue_age_seconds': 0}
    report = evaluate_threshold_rules(metrics)
    assert report['status'] == 'CRITICAL'
    assert report['breaches'][0]['rule'] == 'DEAD_LETTERS_EXISTS'


def test_phase11_requeue_rejects_non_dead_jobs():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
                                     connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            user = User(email='ops@example.test', full_name='Ops', password_hash='x', role='admin',
                        status='active', is_active=True)
            session.add(user); await session.flush()
            event = OutboxEvent(aggregate_id='test', event_type='DELIVER_NOTIFICATION', payload={},
                                idempotency_key='ops-test-1', status='sent', attempts=1)
            session.add(event); await session.flush()
            with pytest.raises(InvalidStateTransition):
                await requeue_failed_job(session, user, event.id, confirmed=True)
        await engine.dispose()
    asyncio.run(run())


def test_admin_rules_are_versioned_and_audited():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
                                     connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            actor = User(email='rule-admin@example.test', full_name='Rule Admin', password_hash='x',
                         role='admin', status='active', is_active=True)
            session.add(actor); await session.flush()
            created = await create_rule(session, actor, 'amount_limit', 'Amount policy', {'max': 500})
            updated = await append_version(session, actor, created['id'], {'max': 750})
            rules = await list_rules(session)
            assert updated['version'] == 2
            assert [item['version'] for item in rules[0]['versions']] == [2, 1]
            assert rules[0]['versions'][0]['policy'] == {'max': 750}
            from app.models.audit_log import AuditLog
            assert await session.scalar(select(AuditLog.id).where(AuditLog.entity == 'automation_rule'))
        await engine.dispose()
    asyncio.run(run())
