import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import InvalidStateTransition
from app.core.enums import AuthorizationState, ExecutionState, FDRStatus, LifecycleState, VerificationLevel, Role, TrustBadge
from app.models import FDR, Institution, User
from app.models.document import Document
from app.models.workflow import ApprovalRecord, OutboxEvent, WorkflowCheckpoint, WorkflowEvent, WorkflowInstance, WorkflowNodeExecution
from app.schemas.fdr import FDRCreate
from app.services.fdr_service import create_fdr, transition
from app.services.refund_service import create_refund, decide
from app.services.workflow_state_service import replay_from_checkpoint, sync_legacy_status
from app.services import ocr_service, bank_verification_service
from app.integrations import storage_client
from app.schemas.verification import OcrResult, BankVerifyResponse
from app.workers import tasks_workflow
from app.schemas.refund import RefundCreate
from app.schemas.workflow import ApprovalRequest
from app.services.workflow_action_service import submit_approval
from app.services.workflow_state_service import LEGACY_STATUS_TO_LIFECYCLE


def test_legacy_status_mapping_keeps_business_and_execution_states_distinct():
    assert LEGACY_STATUS_TO_LIFECYCLE[FDRStatus.SUBMITTED.value] == LifecycleState.SUBMITTED.value
    assert LEGACY_STATUS_TO_LIFECYCLE[FDRStatus.VERIFIED.value] == LifecycleState.ACCEPTED.value
    assert LEGACY_STATUS_TO_LIFECYCLE[FDRStatus.RELEASE_REQUESTED.value] == LifecycleState.AWAITING_RELEASE_DECISION.value
    assert ExecutionState.NOT_STARTED.value != LifecycleState.SUBMITTED.value
    assert AuthorizationState.PENDING.value != VerificationLevel.MOCK_VERIFIED.value


def test_new_fdr_dual_writes_lifecycle_and_human_approval_history():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution = Institution(aicte_id='AICTE-WF-001', name='Workflow College', state='Delhi',
                head_name='Principal', contact_email='workflow@example.test', contact_phone='9000000001', status='active')
            session.add(institution); await session.flush()
            official = User(email='official-workflow@example.test', full_name='Official', password_hash='unused',
                role=Role.AICTE_OFFICIAL.value, institution_id=None, status='active', is_active=True)
            session.add(official); await session.flush()
            fdr = await create_fdr(session, FDRCreate(fdr_number='WFDR-001', bank_name='SBI', amount=Decimal('100000'),
                issue_date=date.today()-timedelta(days=365), maturity_date=date.today()+timedelta(days=30),
                holder='Workflow College'), institution.id, official.id)
            instance = await session.scalar(select(WorkflowInstance).where(WorkflowInstance.fdr_id == fdr.id))
            assert instance.lifecycle_state == LifecycleState.SUBMITTED.value
            assert instance.execution_state == ExecutionState.NOT_STARTED.value
            assert instance.authorization_state == AuthorizationState.NOT_REQUIRED.value
            assert fdr.verification_level == VerificationLevel.DECLARED.value

            await transition(session, fdr.id, FDRStatus.UNDER_SCRUTINY, official.id, 'Review started')
            instance.lifecycle_state = LifecycleState.AWAITING_OFFICIAL_DECISION.value
            instance.execution_state = ExecutionState.WAITING_HUMAN.value
            await transition(session, fdr.id, FDRStatus.VERIFIED, official.id, 'Instrument details reviewed')
            await session.flush()
            assert fdr.status == FDRStatus.VERIFIED.value
            assert fdr.lifecycle_state == LifecycleState.ACCEPTED.value
            assert fdr.authorization_state == AuthorizationState.APPROVED.value
            assert fdr.verification_level == VerificationLevel.HUMAN_SCRUTINIZED.value
            decisions = list((await session.scalars(select(ApprovalRecord).where(ApprovalRecord.fdr_id == fdr.id))).all())
            events = list((await session.scalars(select(WorkflowEvent).where(WorkflowEvent.workflow_instance_id == instance.id))).all())
            assert len(decisions) == 1 and decisions[0].decision == 'approve'
            assert len(events) == 4
            assert any(event.event_type=='approval.recorded' for event in events)
            await session.commit()
            session.add(WorkflowInstance(fdr_id=fdr.id, institution_id=institution.id, execution_version=2,
                workflow_version='invalid-test', lifecycle_state='not_a_lifecycle_state',
                execution_state=ExecutionState.NOT_STARTED.value,
                authorization_state=AuthorizationState.NOT_REQUIRED.value))
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
        await engine.dispose()
    asyncio.run(run())


def test_release_request_and_rejection_update_all_three_status_dimensions():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution = Institution(aicte_id='AICTE-WF-002', name='Matured College', state='Delhi',
                head_name='Principal', contact_email='matured@example.test', contact_phone='9000000003', status='active')
            session.add(institution); await session.flush()
            official = User(email='official-release@example.test', full_name='Official', password_hash='unused',
                role=Role.AICTE_OFFICIAL.value, institution_id=None, status='active', is_active=True)
            institution_user = User(email='college-release@example.test', full_name='College', password_hash='unused',
                role=Role.INSTITUTION.value, institution_id=institution.id, status='active', is_active=True)
            session.add_all([official, institution_user]); await session.flush()
            fdr = FDR(institution_id=institution.id, fdr_number='WFDR-002', bank_name='SBI', branch='Main',
                amount=500000, issue_date=date.today()-timedelta(days=400), maturity_date=date.today()-timedelta(days=1),
                status=FDRStatus.VERIFIED.value, lifecycle_state=LifecycleState.ACCEPTED.value,
                execution_state=ExecutionState.NOT_STARTED.value, authorization_state=AuthorizationState.APPROVED.value,
                verification_level=VerificationLevel.HUMAN_SCRUTINIZED.value, trust_badge=TrustBadge.BANK_VERIFIED.value,
                declared_data={'fdr_number':'WFDR-002'})
            session.add(fdr); await session.flush()
            await sync_legacy_status(session, fdr, event_type='TEST_IMPORT')
            wf=await session.scalar(select(WorkflowInstance).where(WorkflowInstance.fdr_id==fdr.id))
            wf.execution_state=ExecutionState.WAITING_TIMER.value
            request = await create_refund(session, RefundCreate(fdr_id=fdr.id, reason='Release request'), institution_user.id, institution.id)
            assert fdr.status == FDRStatus.RELEASE_REQUESTED.value
            assert wf.lifecycle_state == LifecycleState.AWAITING_RELEASE_DECISION.value
            assert wf.authorization_state == AuthorizationState.PENDING.value
            await decide(session, request.id, 'rejected', 'Original approval conditions remain outstanding.', official.id)
            assert fdr.status == FDRStatus.VERIFIED.value
            assert wf.lifecycle_state == LifecycleState.RELEASE_REJECTED.value
            assert wf.authorization_state == AuthorizationState.REJECTED.value
            rejection = await session.scalar(select(ApprovalRecord).where(ApprovalRecord.refund_request_id == request.id))
            assert rejection.decision == 'reject'
        await engine.dispose()
    asyncio.run(run())


def test_background_workflow_executes_persisted_nodes_and_waits_for_official(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution = Institution(aicte_id='AICTE-WF-003', name='Worker College', state='Delhi',
                head_name='Principal', contact_email='worker@example.test', contact_phone='9000000005', status='active')
            session.add(institution); await session.flush()
            user = User(email='worker-user@example.test', full_name='College', password_hash='unused',
                role=Role.INSTITUTION.value, institution_id=institution.id, status='active', is_active=True)
            official = User(email='worker-official@example.test', full_name='Official', password_hash='unused',
                role=Role.AICTE_OFFICIAL.value, institution_id=None, status='active', is_active=True)
            session.add_all([user,official]); await session.flush()
            data={'fdr_number':'WFDR-003','bank_name':'SBI','amount':100000.0,'issue_date':(date.today()-timedelta(days=100)).isoformat(),
                'maturity_date':(date.today()+timedelta(days=100)).isoformat(),'holder':'Worker College'}
            fdr=FDR(institution_id=institution.id,fdr_number='WFDR-003',bank_name='SBI',branch='Main',amount=100000,
                issue_date=date.today()-timedelta(days=100),maturity_date=date.today()+timedelta(days=100),status='submitted',
                trust_badge='self_declared',declared_data=data,lifecycle_state='submitted',execution_state='not_started',
                authorization_state='not_required',verification_level='declared')
            session.add(fdr); await session.flush()
            document=Document(fdr_id=fdr.id,doc_type='fdr_scan',s3_key='workflow/test.pdf',content_type='application/pdf',
                uploaded_by=user.id,version_no=1,sha256='a'*64)
            session.add(document); await session.flush()
            workflow=WorkflowInstance(fdr_id=fdr.id,institution_id=institution.id,workflow_version='fdr-case-v1',
                execution_version=1,lifecycle_state='submitted',execution_state='not_started',authorization_state='not_required')
            session.add(workflow); await session.commit()

        async def fake_ocr(*args, **kwargs):
            return OcrResult(fdr_number='WFDR-003',bank_name='SBI',holder_name='Worker College',amount=Decimal('100000'),
                issue_date=date.today()-timedelta(days=100),maturity_date=date.today()+timedelta(days=100),confidence=1.0)
        async def fake_bank(*args): return BankVerifyResponse(found=False)
        monkeypatch.setattr(tasks_workflow, 'SessionLocal', factory)
        monkeypatch.setattr(storage_client, 'get', lambda key: b'%PDF-test')
        monkeypatch.setattr(ocr_service, 'extract_fdr_fields', fake_ocr)
        monkeypatch.setattr(bank_verification_service, 'verify_with_bank', fake_bank)
        await tasks_workflow._process_workflow(workflow.id)
        async with factory() as session:
            wf=await session.get(WorkflowInstance,workflow.id)
            assert wf.execution_state == ExecutionState.WAITING_HUMAN.value
            assert wf.lifecycle_state == LifecycleState.READY_FOR_SCRUTINY.value
            nodes=list((await session.scalars(select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_instance_id==workflow.id).order_by(WorkflowNodeExecution.id))).all())
            assert [node.node_key for node in nodes] == ['extract_document','validate_fields','route_case']
            assert all(node.status=='succeeded' for node in nodes)
            assert await session.scalar(select(func.count(WorkflowCheckpoint.id)).where(
                WorkflowCheckpoint.workflow_instance_id==workflow.id)) == 3
            before=len(nodes)
        # At-least-once duplicate task delivery while waiting is a no-op.
        await tasks_workflow._process_workflow(workflow.id)
        async with factory() as session:
            assert await session.scalar(select(func.count(WorkflowNodeExecution.id)).where(
                WorkflowNodeExecution.workflow_instance_id==workflow.id)) == before
            route_run=await session.scalar(select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_instance_id==workflow.id,
                WorkflowNodeExecution.node_key=='route_case').order_by(WorkflowNodeExecution.attempt.desc()).limit(1))
            route_checkpoint=await session.scalar(select(WorkflowCheckpoint).where(
                WorkflowCheckpoint.node_execution_id==route_run.id))
            replay=await replay_from_checkpoint(session,workflow.id,route_checkpoint.id,official.id,'aicte_official',
                'Review route replay',acknowledge_side_effects=False)
            await session.commit()
            assert replay.execution_state == ExecutionState.RETRYING.value
        await tasks_workflow._process_workflow(workflow.id)
        async with factory() as session:
            route_runs=list((await session.scalars(select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_instance_id==workflow.id,
                WorkflowNodeExecution.node_key=='route_case').order_by(WorkflowNodeExecution.attempt))).all())
            assert len(route_runs)==2 and route_runs[1].replay_of_id==route_runs[0].id
        await engine.dispose()
    asyncio.run(run())


def test_replay_requires_explicit_ack_for_non_idempotent_downstream(monkeypatch):
    from dataclasses import replace
    from app.workflows import definition
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-UNSAFE-1',name='Replay',state='Delhi',head_name='P',
                contact_email='replay@example.test',contact_phone='9000000008',status='active')
            session.add(institution);await session.flush()
            user=User(email='replay-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            fdr=FDR(institution_id=institution.id,fdr_number='R-1',bank_name='SBI',branch='',amount=10,
                issue_date=date.today(),maturity_date=date.today()+timedelta(days=1),status='submitted',
                trust_badge='self_declared',declared_data={})
            session.add_all([user,fdr]);await session.flush()
            doc=Document(fdr_id=fdr.id,doc_type='fdr_scan',s3_key='replay',content_type='application/pdf',uploaded_by=user.id)
            session.add(doc);await session.flush()
            wf=WorkflowInstance(fdr_id=fdr.id,institution_id=institution.id,workflow_version='v1',execution_version=1,
                lifecycle_state='submitted',execution_state='waiting_human',authorization_state='pending')
            session.add(wf);await session.flush()
            node=WorkflowNodeExecution(workflow_instance_id=wf.id,node_key='extract_document',attempt=1,status='succeeded',
                workflow_version='v1',input_ref={'document_id':doc.id})
            session.add(node);await session.flush()
            cp=WorkflowCheckpoint(workflow_instance_id=wf.id,node_execution_id=node.id,state_snapshot={'input_ref':{'document_id':doc.id}})
            session.add(cp);await session.commit()
            monkeypatch.setitem(definition.NODES,'route_case',replace(definition.NODES['route_case'],side_effect_class='non_idempotent_effect'))
            with pytest.raises(InvalidStateTransition,match='SIDE_EFFECT_CONFIRMATION_REQUIRED'):
                await replay_from_checkpoint(session,wf.id,cp.id,user.id,user.role,'Need acknowledge')
            replay=await replay_from_checkpoint(session,wf.id,cp.id,user.id,user.role,'Confirmed replay',True,'unsafe-replay-key')
            assert replay.execution_state==ExecutionState.RETRYING.value
        await engine.dispose()
    asyncio.run(run())


def test_expired_worker_lease_marks_attempt_lost_and_requeues(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-LEASE-001',name='Lease College',state='Delhi',
                head_name='Principal',contact_email='lease@example.test',contact_phone='9000000006',status='active')
            session.add(institution); await session.flush()
            fdr=FDR(institution_id=institution.id,fdr_number='LEASE-001',bank_name='SBI',branch='Main',amount=100000,
                issue_date=date.today(),maturity_date=date.today()+timedelta(days=10),status='submitted',trust_badge='self_declared',declared_data={})
            session.add(fdr); await session.flush()
            now=datetime.now(timezone.utc)
            workflow=WorkflowInstance(fdr_id=fdr.id,institution_id=institution.id,workflow_version='fdr-case-v1',
                execution_version=1,lifecycle_state='extracting',execution_state='running',authorization_state='not_required',
                current_node='extract_document',worker_lease_until=now-timedelta(seconds=5))
            session.add(workflow); await session.flush()
            node=WorkflowNodeExecution(workflow_instance_id=workflow.id,node_key='extract_document',attempt=1,
                status='running',started_at=now-timedelta(minutes=5),workflow_version='fdr-case-v1')
            session.add(node); await session.commit()
        monkeypatch.setattr(tasks_workflow, 'SessionLocal', factory)
        recovered=await tasks_workflow._recover_expired_leases()
        assert recovered == 1
        async with factory() as session:
            wf=await session.get(WorkflowInstance,workflow.id)
            failed=await session.get(WorkflowNodeExecution,node.id)
            outbox=await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id==str(workflow.id)))
            assert wf.execution_state == ExecutionState.RETRYING.value
            assert failed.status == 'failed' and failed.error_class == 'WORKER_LOST'
            assert outbox.status == 'pending'
        await engine.dispose()
    asyncio.run(run())


def test_human_approval_is_idempotent_audited_and_notifies_institution():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-APPROVE-001',name='Approval College',state='Delhi',
                head_name='Principal',contact_email='approve@example.test',contact_phone='9000000009',status='active')
            session.add(institution);await session.flush()
            official=User(email='approval-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(official);await session.flush()
            fdr=FDR(institution_id=institution.id,fdr_number='APPROVE-1',bank_name='SBI',branch='Main',amount=100,
                issue_date=date.today()-timedelta(days=10),maturity_date=date.today()+timedelta(days=40),
                status=FDRStatus.SUBMITTED.value,trust_badge=TrustBadge.BANK_VERIFIED.value,declared_data={})
            session.add(fdr);await session.flush()
            workflow=WorkflowInstance(fdr_id=fdr.id,institution_id=institution.id,workflow_version='v1',execution_version=1,
                lifecycle_state=LifecycleState.READY_FOR_SCRUTINY.value,execution_state=ExecutionState.WAITING_HUMAN.value,
                authorization_state=AuthorizationState.PENDING.value)
            session.add(workflow);await session.flush()
            body=ApprovalRequest(fdr_id=fdr.id,request_type='fdr_scrutiny',decision='approve',
                rationale='Declared fields agree with reviewed source records.',idempotency_key='approve-case-0001')
            first=await submit_approval(session,official,body)
            second=await submit_approval(session,official,body)
            assert first['decision']=='approve' and not first['duplicate']
            assert second['duplicate']
            await session.commit()
            assert fdr.status==FDRStatus.VERIFIED.value
            approval=await session.scalar(select(ApprovalRecord).where(ApprovalRecord.idempotency_key==body.idempotency_key))
            assert approval and approval.rationale==body.rationale
            notice=next((row for row in (await session.scalars(select(OutboxEvent).where(
                OutboxEvent.event_type=='DELIVER_NOTIFICATION').order_by(OutboxEvent.id.desc()))).all()
                if row.payload.get('recipient')==institution.contact_email),None)
            assert notice and notice.payload['recipient']==institution.contact_email
        await engine.dispose()
    asyncio.run(run())
