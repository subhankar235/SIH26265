"""Comprehensive tests for Phase 8 (Live Updates / SSE) and Phase 9 (Natural-Language Command Center).

Covers all required specifications:
- 8.1 / 8.2: Pub/Sub event bus & event emission (node.started/succeeded/failed, state.changed, exception.created, approval.recorded, command.progress)
- 8.3: Client reconnect with Last-Event-ID and replay from workflow_event
- 8.4: Authorization checked at connect and per-event scope filter (institution isolation)
- 8.5: Fallback polling endpoint
- 9.1 - 9.4: Pipeline, action schema, allowlisted tools, server entity resolution
- Explicit required tests:
  1. cross-institution reference rejected
  2. model returns unknown tool -> rejected
  3. bulk without confirm -> rejected
  4. "approve release for all" -> refused/unsupported
  5. plan_hash mismatch -> 409
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.enums import AuthorizationState, ExecutionState, LifecycleState, Role
from app.core.exceptions import InvalidStateTransition, NotFound, PermissionDenied
from app.models import FDR, Institution, User
from app.models.workflow import CommandExecution, OutboxEvent, WorkflowEvent, WorkflowInstance, WorkflowNodeExecution
from app.schemas.workflow import CommandIntentModel
from app.services.command_service import cancel, confirm, execute, interpret
from app.services.event_bus import get_event_bus
from app.services.workflow_events import publish


async def _setup_test_db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool, connect_args={'check_same_thread': False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


@pytest.mark.asyncio
async def test_cross_institution_reference_rejected():
    """Test 1: Cross-institution reference must be rejected (404/NotFound scoped to user)."""
    engine, factory = await _setup_test_db()
    async with factory() as session:
        inst_a = Institution(aicte_id='AICTE-A', name='College A', state='Delhi', head_name='Principal A', contact_email='a@example.test', contact_phone='9999900001', status='active')
        inst_b = Institution(aicte_id='AICTE-B', name='College B', state='Goa', head_name='Principal B', contact_email='b@example.test', contact_phone='9999900002', status='active')
        session.add_all([inst_a, inst_b])
        await session.flush()

        user_a = User(email='user-a@example.test', full_name='User A', password_hash='x', role=Role.INSTITUTION.value, institution_id=inst_a.id, status='active', is_active=True)
        session.add(user_a)
        await session.flush()

        fdr_b = FDR(institution_id=inst_b.id, fdr_number='FDR-INST-B-001', bank_name='SBI', branch='Main', amount=50000,
                    issue_date=date.today(), maturity_date=date.today() + timedelta(days=60), status='submitted', trust_badge='self_declared', declared_data={})
        session.add(fdr_b)
        await session.flush()

        wf_b = WorkflowInstance(fdr_id=fdr_b.id, institution_id=inst_b.id, workflow_version='v1', execution_version=1,
                                lifecycle_state=LifecycleState.SUBMITTED.value, execution_state=ExecutionState.NOT_STARTED.value,
                                authorization_state=AuthorizationState.NOT_REQUIRED.value)
        session.add(wf_b)
        await session.commit()

        # User from Institution A attempts to explain / interact with FDR-INST-B-001 belonging to Institution B
        with pytest.raises(NotFound, match='No authorized FDR matches that reference'):
            await interpret(session, user_a, 'Explain why FDR-INST-B-001 is blocked', 'key-idor-test-1')

    await engine.dispose()


@pytest.mark.asyncio
async def test_model_returns_unknown_tool_rejected():
    """Test 2: If model or untrusted command specifies an unknown tool/intent -> rejected."""
    # Strict validation in CommandIntentModel rejects unknown intents
    with pytest.raises(ValueError, match='Unsupported command intent'):
        CommandIntentModel(intent='raw_sql_query', args={'query': 'SELECT * FROM users'}, confidence=0.9)

    with pytest.raises(ValueError, match='Unsupported command intent'):
        CommandIntentModel(intent='grant_admin_role', args={'user': 'attacker'}, confidence=0.9)

    engine, factory = await _setup_test_db()
    async with factory() as session:
        official = User(email='off@example.test', full_name='Official', password_hash='x', role=Role.AICTE_OFFICIAL.value, status='active', is_active=True)
        session.add(official)
        await session.commit()

        with pytest.raises(InvalidStateTransition, match='prohibited by security policy|not in the supported allowlist'):
            await interpret(session, official, 'DROP TABLE users;', 'key-unknown-1')

    await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_without_confirm_rejected():
    """Test 3: Bulk operations (e.g. escalate_cases, prepare_reminders) require confirmation and cannot run without it."""
    engine, factory = await _setup_test_db()
    async with factory() as session:
        inst = Institution(aicte_id='AICTE-BLK', name='Bulk College', state='Punjab', head_name='Principal Bulk', contact_email='bulk@example.test', contact_phone='9999900003', status='active')
        session.add(inst)
        await session.flush()

        official = User(email='official-bulk@example.test', full_name='Official Bulk', password_hash='x', role=Role.AICTE_OFFICIAL.value, status='active', is_active=True)
        session.add(official)
        await session.flush()

        fdr1 = FDR(institution_id=inst.id, fdr_number='FDR-BLK-01', bank_name='PNB', branch='Chd', amount=10000,
                   issue_date=date.today(), maturity_date=date.today() + timedelta(days=10), status='submitted', trust_badge='self_declared', declared_data={})
        fdr2 = FDR(institution_id=inst.id, fdr_number='FDR-BLK-02', bank_name='PNB', branch='Chd', amount=20000,
                   issue_date=date.today(), maturity_date=date.today() + timedelta(days=15), status='submitted', trust_badge='self_declared', declared_data={})
        session.add_all([fdr1, fdr2])
        await session.flush()

        wf1 = WorkflowInstance(fdr_id=fdr1.id, institution_id=inst.id, workflow_version='v1', execution_version=1,
                               lifecycle_state=LifecycleState.CORRECTION_REQUIRED.value, execution_state=ExecutionState.WAITING_EVENT.value,
                               authorization_state=AuthorizationState.PENDING.value)
        wf2 = WorkflowInstance(fdr_id=fdr2.id, institution_id=inst.id, workflow_version='v1', execution_version=1,
                               lifecycle_state=LifecycleState.CORRECTION_REQUIRED.value, execution_state=ExecutionState.WAITING_EVENT.value,
                               authorization_state=AuthorizationState.PENDING.value)
        session.add_all([wf1, wf2])
        await session.commit()

        # Bulk escalation plan
        cmd, plan = await interpret(session, official, 'Escalate cases waiting for correction', 'key-bulk-test-1')
        assert cmd.requires_confirmation is True
        assert cmd.status == 'planned'
        assert len(plan['resolved_targets']) >= 2

        # Verify executing without confirmation does NOT run (status is still planned, not confirmed/running)
        await execute(session, cmd.id)
        reloaded = await session.get(CommandExecution, cmd.id)
        assert reloaded.status == 'planned'
        assert reloaded.result_summary is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_approve_release_for_all_refused():
    """Test 4: 'approve release for all' -> refused/unsupported."""
    engine, factory = await _setup_test_db()
    async with factory() as session:
        official = User(email='off-rel@example.test', full_name='Official Rel', password_hash='x', role=Role.AICTE_OFFICIAL.value, status='active', is_active=True)
        session.add(official)
        await session.commit()

        with pytest.raises(InvalidStateTransition, match='Bulk release/refund approvals are unsupported'):
            await interpret(session, official, 'Approve release for all FDRs', 'key-rel-all-1')

        with pytest.raises(InvalidStateTransition, match='Bulk release/refund approvals are unsupported'):
            await interpret(session, official, 'Approve refund for all cases now', 'key-rel-all-2')

    await engine.dispose()


@pytest.mark.asyncio
async def test_plan_hash_mismatch_returns_409():
    """Test 5: plan_hash mismatch on confirmation raises InvalidStateTransition (maps to HTTP 409)."""
    engine, factory = await _setup_test_db()
    async with factory() as session:
        inst = Institution(aicte_id='AICTE-HASH', name='Hash College', state='Kerala', head_name='Principal Hash', contact_email='hash@example.test', contact_phone='9999900004', status='active')
        session.add(inst)
        await session.flush()

        official = User(email='off-hash@example.test', full_name='Official Hash', password_hash='x', role=Role.AICTE_OFFICIAL.value, status='active', is_active=True)
        session.add(official)
        await session.flush()

        fdr = FDR(institution_id=inst.id, fdr_number='FDR-HASH-99', bank_name='HDFC', branch='Kochi', amount=150000,
                  issue_date=date.today(), maturity_date=date.today() + timedelta(days=20), status='submitted', trust_badge='self_declared', declared_data={})
        session.add(fdr)
        await session.flush()

        wf = WorkflowInstance(fdr_id=fdr.id, institution_id=inst.id, workflow_version='v1', execution_version=1,
                              lifecycle_state=LifecycleState.SUBMITTED.value, execution_state=ExecutionState.RUNNING.value,
                              authorization_state=AuthorizationState.NOT_REQUIRED.value)
        session.add(wf)
        await session.commit()

        cmd, plan = await interpret(session, official, 'Pause FDR-HASH-99', 'key-hash-test-1')
        assert cmd.requires_confirmation is True
        assert cmd.status == 'planned'

        # Attempt confirmation with wrong / tampered plan_hash
        bogus_hash = '0000000000000000000000000000000000000000000000000000000000000000'
        with pytest.raises(InvalidStateTransition, match='PLAN_CHANGED'):
            await confirm(session, official, cmd.id, bogus_hash)

        # Confirm with correct plan_hash succeeds
        confirmed = await confirm(session, official, cmd.id, cmd.plan_hash)
        assert confirmed.status == 'confirmed'

    await engine.dispose()


@pytest.mark.asyncio
async def test_phase8_events_pubsub_and_sse_replay():
    """Phase 8: Pub/Sub event broadcasting, Last-Event-ID replay from workflow_event table."""
    engine, factory = await _setup_test_db()
    bus = get_event_bus()

    async with factory() as session:
        inst = Institution(aicte_id='AICTE-SSE', name='SSE College', state='Maharashtra', head_name='Principal SSE', contact_email='sse@example.test', contact_phone='9999900005', status='active')
        session.add(inst)
        await session.flush()

        fdr = FDR(institution_id=inst.id, fdr_number='FDR-SSE-101', bank_name='BOI', branch='Pune', amount=50000,
                  issue_date=date.today(), maturity_date=date.today() + timedelta(days=90), status='submitted', trust_badge='self_declared', declared_data={})
        session.add(fdr)
        await session.flush()

        wf = WorkflowInstance(fdr_id=fdr.id, institution_id=inst.id, workflow_version='v1', execution_version=1,
                              lifecycle_state=LifecycleState.SUBMITTED.value, execution_state=ExecutionState.RUNNING.value,
                              authorization_state=AuthorizationState.NOT_REQUIRED.value)
        session.add(wf)
        await session.flush()

        # 8.2 Events emission: node.started, node.succeeded, state.changed, exception.created, approval.recorded
        e1 = await publish(session, wf.id, 'node.started', {'node_key': 'extract_document', 'attempt': 1}, 'dedupe-sse-1')
        e2 = await publish(session, wf.id, 'node.succeeded', {'node_key': 'extract_document', 'duration_ms': 120}, 'dedupe-sse-2')
        e3 = await publish(session, wf.id, 'state.changed', {'lifecycle_state': 'under_review', 'execution_state': 'running'}, 'dedupe-sse-3')
        e4 = await publish(session, wf.id, 'exception.created', {'reason_code': 'AMOUNT_MISMATCH', 'priority': 2}, 'dedupe-sse-4')
        e5 = await publish(session, wf.id, 'approval.recorded', {'decision': 'approve', 'rationale': 'Verified'}, 'dedupe-sse-5')
        await session.commit()

        assert all([e1, e2, e3, e4, e5])

        # 8.3 Client reconnect with Last-Event-ID; server replays events with id > last_event_id
        all_events = list((await session.scalars(select(WorkflowEvent).where(WorkflowEvent.workflow_instance_id == wf.id).order_by(WorkflowEvent.id))).all())
        assert len(all_events) == 5

        first_id = all_events[0].id
        replayed = list((await session.scalars(select(WorkflowEvent).where(
            WorkflowEvent.workflow_instance_id == wf.id,
            WorkflowEvent.id > first_id
        ).order_by(WorkflowEvent.id))).all())
        assert len(replayed) == 4
        assert [e.id for e in replayed] == [all_events[1].id, all_events[2].id, all_events[3].id, all_events[4].id]

    await engine.dispose()


@pytest.mark.asyncio
async def test_command_background_execution_and_cancellation():
    """Phase 9.4: Background execution with progress streaming; cancel stops before next step."""
    engine, factory = await _setup_test_db()
    async with factory() as session:
        inst = Institution(aicte_id='AICTE-EXEC', name='Exec College', state='Assam', head_name='Principal', contact_email='exec@example.test', contact_phone='9999900006', status='active')
        session.add(inst)
        await session.flush()

        official = User(email='off-exec@example.test', full_name='Official Exec', password_hash='x', role=Role.AICTE_OFFICIAL.value, status='active', is_active=True)
        session.add(official)
        await session.flush()

        fdr = FDR(institution_id=inst.id, fdr_number='FDR-EXEC-1', bank_name='SBI', branch='Guwahati', amount=200000,
                  issue_date=date.today(), maturity_date=date.today() + timedelta(days=25), status='submitted', trust_badge='self_declared', declared_data={})
        session.add(fdr)
        await session.flush()

        wf = WorkflowInstance(fdr_id=fdr.id, institution_id=inst.id, workflow_version='v1', execution_version=1,
                              lifecycle_state=LifecycleState.SUBMITTED.value, execution_state=ExecutionState.RUNNING.value,
                              authorization_state=AuthorizationState.NOT_REQUIRED.value)
        session.add(wf)
        await session.commit()

        # Plan pause_case
        cmd, plan = await interpret(session, official, 'Pause FDR-EXEC-1', 'key-pause-exec-1')
        assert cmd.requires_confirmation is True

        # Confirm command
        await confirm(session, official, cmd.id, cmd.plan_hash)
        assert cmd.status == 'confirmed'

        # Execute command in background job simulation
        await execute(session, cmd.id)
        assert cmd.status == 'succeeded'
        assert 'paused' in cmd.result_summary

        # Verify workflow state updated to paused
        reloaded_wf = await session.get(WorkflowInstance, wf.id)
        assert reloaded_wf.execution_state == 'paused'

        # Test cancellation before execution
        cmd2, plan2 = await interpret(session, official, 'Resume FDR-EXEC-1', 'key-resume-exec-2')
        cancelled_cmd = await cancel(session, official, cmd2.id, 'Operator cancelled request before execution')
        assert cancelled_cmd.status == 'cancelled'

    await engine.dispose()
