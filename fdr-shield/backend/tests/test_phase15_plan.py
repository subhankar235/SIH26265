import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.clock import business_today
from app.core.database import Base
from app.core.enums import ExecutionState, FDRStatus
from app.core.exceptions import InvalidStateTransition
from app.models import FDR, Institution, User
from app.models.notification import Notification
from app.models.document import Document
from app.models.workflow import (CorrectionRequest, NotificationDeliveryAttempt, OutboxEvent,
    VerificationRun, WorkflowEvent, WorkflowInstance, WorkflowNodeExecution)
from app.schemas.fdr import FDRCreate
from app.services import outbox_service
from app.services import local_execution_service
from app.services.fdr_service import create_fdr
from app.services.notification_service import stage_for
from app.services.document_service import store_upload
from app.services.verification_service import get_report
from app.workflows.transitions import ALLOWED, transition


def test_workflow_transition_table_accepts_exactly_declared_pairs():
    states={state for state,_ in ALLOWED}
    events={event for _,event in ALLOWED}
    for state,event in ALLOWED:
        role='aicte_official' if event in {'OFFICIAL_APPROVED','OFFICIAL_REQUESTED_CORRECTION','PAUSE','RESUME'} else 'system'
        result=transition(SimpleNamespace(execution_state=state),event,actor_role=role)
        assert result==ALLOWED[(state,event)]
    for state in {item.value for item in ExecutionState}:
        for event in events:
            if (state,event) in ALLOWED: continue
            with pytest.raises(InvalidStateTransition):
                transition(SimpleNamespace(execution_state=state),event,actor_role='aicte_official')


def test_business_date_uses_ist_boundary_and_leap_day_offsets():
    before=datetime(2026,1,1,18,29,tzinfo=timezone.utc)
    after=datetime(2026,1,1,18,30,tzinfo=timezone.utc)
    assert business_today(before)==date(2026,1,1)
    assert business_today(after)==date(2026,1,2)
    leap_before=datetime(2024,2,28,18,29,tzinfo=timezone.utc)
    leap_boundary=datetime(2024,2,28,18,30,tzinfo=timezone.utc)
    maturity=date(2024,2,29)
    assert (maturity-business_today(leap_before)).days==1
    assert asyncio.run(stage_for((maturity-business_today(leap_before)).days)).value=='T-30'
    assert (maturity-business_today(leap_boundary)).days==0
    assert asyncio.run(stage_for((maturity-business_today(leap_boundary)).days)).value=='T-0'


def test_submit_creates_case_workflow_event_and_outbox_in_one_transaction():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            inst=Institution(aicte_id='P15-SUBMIT',name='Submit College',state='Delhi',head_name='P',
                contact_email='submit@example.test',contact_phone='9000000010',status='active')
            actor=User(email='submit-user@example.test',full_name='Submit User',password_hash='x',
                role='institution',institution_id=1,status='active',is_active=True)
            session.add(inst);await session.flush();actor.institution_id=inst.id;session.add(actor);await session.flush()
            await create_fdr(session,FDRCreate(fdr_number='P15-FDR-1',bank_name='SBI',amount=Decimal('1000'),
                issue_date=date.today()-timedelta(days=10),maturity_date=date.today()+timedelta(days=365),holder='College'),inst.id,actor.id)
            fdr=await session.scalar(select(FDR).where(FDR.fdr_number=='P15-FDR-1'))
            workflow=await session.scalar(select(WorkflowInstance).where(WorkflowInstance.fdr_id==fdr.id))
            assert fdr and workflow
            assert await session.scalar(select(func.count(WorkflowEvent.id)).where(WorkflowEvent.workflow_instance_id==workflow.id))>=1
            assert await session.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.aggregate_id==str(workflow.id)))==1
            await session.rollback()
        async with factory() as verify:
            assert await verify.scalar(select(func.count(FDR.id)).where(FDR.fdr_number=='P15-FDR-1'))==0
            assert await verify.scalar(select(func.count(WorkflowInstance.id)))==0
            assert await verify.scalar(select(func.count(WorkflowEvent.id)))==0
            assert await verify.scalar(select(func.count(OutboxEvent.id)))==0
        await engine.dispose()
    asyncio.run(run())


def test_local_eager_mode_runs_workflow_without_broker(monkeypatch):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(local_execution_service,'get_settings',
            lambda:SimpleNamespace(celery_task_always_eager=True))
        from app.workers import tasks_workflow
        monkeypatch.setattr(tasks_workflow,'SessionLocal',factory)
        calls=[]
        async def process_inline(workflow_id):
            calls.append(workflow_id)
            async with factory() as worker_session:
                workflow=await worker_session.get(WorkflowInstance,workflow_id)
                workflow.execution_state=ExecutionState.WAITING_HUMAN.value
                await worker_session.commit()
        monkeypatch.setattr(tasks_workflow,'_process_workflow',process_inline)
        async with factory() as session:
            institution=Institution(aicte_id='LOCAL-INLINE',name='Inline College',state='Delhi',
                head_name='P',contact_email='inline@example.test',contact_phone='9000000012',status='active')
            session.add(institution);await session.flush()
            actor=User(email='inline-user@example.test',full_name='Inline User',password_hash='x',
                role='institution',institution_id=institution.id,status='active',is_active=True)
            session.add(actor);await session.flush()
            fdr=await create_fdr(session,FDRCreate(fdr_number='LOCAL-INLINE-1',bank_name='SBI',
                amount=Decimal('1000'),issue_date=date.today()-timedelta(days=10),
                maturity_date=date.today()+timedelta(days=365),holder='College'),institution.id,actor.id)
            workflow=await session.scalar(select(WorkflowInstance).where(WorkflowInstance.fdr_id==fdr.id))
            assert workflow
            assert await local_execution_service.run_inline_workflow_if_enabled(session,fdr.id)
            assert calls==[workflow.id]
            assert workflow.execution_state==ExecutionState.WAITING_HUMAN.value
            events=list((await session.scalars(select(OutboxEvent).where(
                OutboxEvent.aggregate_id==str(workflow.id)))).all())
            assert events and all(event.status=='sent' for event in events)
        await engine.dispose()
    asyncio.run(run())


def test_notification_provider_outage_retries_then_sends_once(monkeypatch):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        sends=[]
        async def unavailable(payload): sends.append('failed');return False
        async def available(payload): sends.append('accepted');return True
        monkeypatch.setattr(outbox_service,'_send_notification',unavailable)
        async with factory() as session:
            inst=Institution(aicte_id='P15-OUTBOX',name='Outbox College',state='Delhi',head_name='P',
                contact_email='outbox@example.test',contact_phone='9000000011',status='active')
            session.add(inst);await session.flush()
            fdr=FDR(institution_id=inst.id,fdr_number='P15-OUTBOX-1',bank_name='SBI',branch='',amount=100,
                issue_date=date.today(),maturity_date=date.today()+timedelta(days=30),status='submitted',
                trust_badge='self_declared',declared_data={})
            session.add(fdr);await session.flush()
            note=Notification(fdr_id=fdr.id,stage='T-30',channel='email',recipient=inst.contact_email,status='queued')
            session.add(note);await session.flush()
            payload={'notification_id':note.id,'channel':'email','recipient':note.recipient,'subject':'test','body':'test'}
            event=OutboxEvent(aggregate_id=str(fdr.id),event_type='DELIVER_NOTIFICATION',payload=payload,
                idempotency_key='phase15-notify-once',status='pending',attempts=0,
                next_attempt_at=datetime.now(timezone.utc))
            session.add(event);await session.commit()
            first=await outbox_service.dispatch_batch(session);await session.commit()
            assert first['retried']==1 and sends==['failed']
            event=await session.get(OutboxEvent,event.id);event.next_attempt_at=datetime.now(timezone.utc)-timedelta(seconds=1)
            await session.commit();monkeypatch.setattr(outbox_service,'_send_notification',available)
            second=await outbox_service.dispatch_batch(session);await session.commit()
            assert second['sent']==1 and sends==['failed','accepted']
            attempts=list((await session.scalars(select(NotificationDeliveryAttempt).where(
                NotificationDeliveryAttempt.notification_id==note.id).order_by(NotificationDeliveryAttempt.attempt_no))).all())
            assert [item.status for item in attempts]==['failed','sent']
            assert (await session.get(Notification,note.id)).status=='sent'
            await session.commit()
            third=await outbox_service.dispatch_batch(session);await session.commit()
            assert third['claimed']==0 and sends==['failed','accepted']
        await engine.dispose()
    asyncio.run(run())


def test_worker_crash_after_provider_acceptance_does_not_automatically_duplicate(monkeypatch):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        delivered=[]
        async def provider_accept_then_worker_crashes(payload):
            delivered.append(payload['notification_id'])
            raise SystemExit('simulated process death after send before mark-sent')
        monkeypatch.setattr(outbox_service,'_send_notification',provider_accept_then_worker_crashes)
        async with factory() as session:
            inst=Institution(aicte_id='P15-CRASH',name='Crash College',state='Delhi',head_name='P',
                contact_email='crash@example.test',contact_phone='9000000014',status='active')
            session.add(inst);await session.flush()
            fdr=FDR(institution_id=inst.id,fdr_number='P15-CRASH-1',bank_name='SBI',branch='',amount=100,
                issue_date=date.today(),maturity_date=date.today()+timedelta(days=30),status='submitted',
                trust_badge='self_declared',declared_data={})
            session.add(fdr);await session.flush()
            note=Notification(fdr_id=fdr.id,stage='T-30',channel='email',recipient=inst.contact_email,status='queued')
            session.add(note);await session.flush()
            payload={'notification_id':note.id,'channel':'email','recipient':note.recipient,'subject':'test','body':'test'}
            event=OutboxEvent(aggregate_id=str(fdr.id),event_type='DELIVER_NOTIFICATION',payload=payload,
                idempotency_key='phase15-crash-send',status='pending',attempts=0,next_attempt_at=datetime.now(timezone.utc))
            session.add(event);await session.commit()
            with pytest.raises(SystemExit): await outbox_service.dispatch_batch(session)
            await session.rollback()
        monkeypatch.setattr(outbox_service,'_send_notification',lambda payload: asyncio.sleep(0,result=True))
        async with factory() as session:
            event=await session.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key=='phase15-crash-send'))
            event.locked_until=datetime.now(timezone.utc)-timedelta(seconds=1)
            await session.commit()
            recovered=await outbox_service.dispatch_batch(session);await session.commit()
            assert recovered['dead']==1
            assert delivered==[note.id]
            attempts=list((await session.scalars(select(NotificationDeliveryAttempt).where(
                NotificationDeliveryAttempt.notification_id==note.id))).all())
            assert len(attempts)==1 and attempts[0].status=='uncertain'
            assert event.status=='dead'
        await engine.dispose()
    asyncio.run(run())


def test_correction_upload_resumes_with_new_document_version_and_keeps_old_results(monkeypatch):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        from app.integrations import storage_client,upload_scanner
        async def clean_scan(data): return {'scanned':False,'engine':'test'}
        monkeypatch.setattr(upload_scanner,'scan_upload',clean_scan)
        monkeypatch.setattr(storage_client,'put',lambda *args:None)
        class FakeFile:
            filename='corrected.pdf';content_type='application/pdf'
            async def read(self): return b'%PDF-1.7 corrected content'
        async with factory() as session:
            inst=Institution(aicte_id='P15-CORRECTION',name='Correction College',state='Delhi',head_name='P',
                contact_email='correction@example.test',contact_phone='9000000012',status='active')
            session.add(inst);await session.flush()
            actor=User(email='correction-user@example.test',full_name='Institution User',password_hash='x',
                role='institution',institution_id=inst.id,status='active',is_active=True)
            fdr=FDR(institution_id=inst.id,fdr_number='P15-FDR-CORR',bank_name='SBI',branch='',amount=100,
                issue_date=date.today()-timedelta(days=10),maturity_date=date.today()+timedelta(days=365),
                status='mismatch',lifecycle_state='awaiting_institution',execution_state='waiting_event',
                authorization_state='pending',trust_badge='mismatch',declared_data={'fdr_number':'P15-FDR-CORR'},is_synthetic=False)
            session.add_all([actor,fdr]);await session.flush()
            wf=WorkflowInstance(fdr_id=fdr.id,institution_id=inst.id,workflow_version='fdr-case-v1',execution_version=1,
                lifecycle_state='awaiting_institution',execution_state='waiting_event',authorization_state='pending')
            session.add(wf);await session.flush()
            original=Document(fdr_id=fdr.id,doc_type='fdr_scan',s3_key='old.pdf',content_type='application/pdf',
                uploaded_by=actor.id,version_no=1,sha256='a'*64)
            session.add(original);await session.flush()
            old_run=VerificationRun(fdr_id=fdr.id,document_id=original.id,extraction_engine='test',source='ocr_extraction',
                verification_level='extracted',declared_snapshot={},extracted_fields={},discrepancies=[])
            correction=CorrectionRequest(workflow_instance_id=wf.id,fdr_id=fdr.id,requested_by=actor.id,
                reason='Correct amount field',required_fields=['amount'],status='open')
            session.add_all([old_run,correction]);await session.commit()
            new_doc=await store_upload(session,fdr.id,'fdr_scan',FakeFile(),actor.id)
            assert new_doc.version_no==2 and new_doc.supersedes_document_id==original.id
            assert await session.get(Document,original.id)
            assert await session.get(VerificationRun,old_run.id)
            assert (await session.get(CorrectionRequest,correction.id)).status=='submitted'
            assert wf.execution_state=='running' and wf.lifecycle_state=='extraction_pending'
            assert await session.scalar(select(OutboxEvent.id).where(OutboxEvent.event_type=='WORKFLOW_WAKE'))
        await engine.dispose()
    asyncio.run(run())


def test_first_scan_attached_to_existing_fdr_queues_verification_reprocessing(monkeypatch):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        from app.integrations import storage_client,upload_scanner
        async def clean_scan(data): return {'scanned':False,'engine':'test'}
        monkeypatch.setattr(upload_scanner,'scan_upload',clean_scan)
        monkeypatch.setattr(storage_client,'put',lambda *args:None)
        class FakeFile:
            filename='receipt.pdf';content_type='application/pdf'
            async def read(self): return b'%PDF-1.7 receipt content'
        async with factory() as session:
            inst=Institution(aicte_id='P15-MISSING-SCAN',name='Missing Scan College',state='Delhi',head_name='P',
                contact_email='missing-scan@example.test',contact_phone='9000000013',status='active')
            session.add(inst);await session.flush()
            actor=User(email='missing-scan-user@example.test',full_name='Institution User',password_hash='x',
                role='institution',institution_id=inst.id,status='active',is_active=True)
            fdr=FDR(institution_id=inst.id,fdr_number='P15-FDR-MISSING-SCAN',bank_name='SBI',branch='',amount=100,
                issue_date=date.today()-timedelta(days=10),maturity_date=date.today()+timedelta(days=365),
                status='submitted',lifecycle_state='submitted',execution_state='completed',
                authorization_state='not_required',trust_badge='self_declared',declared_data={},is_synthetic=False)
            session.add_all([actor,fdr]);await session.flush()
            old_workflow=WorkflowInstance(fdr_id=fdr.id,institution_id=inst.id,workflow_version='fdr-case-v1',
                execution_version=1,lifecycle_state='submitted',execution_state='completed',
                authorization_state='not_required')
            session.add(old_workflow);await session.commit()

            document=await store_upload(session,fdr.id,'fdr_scan',FakeFile(),actor.id)
            workflows=list((await session.scalars(select(WorkflowInstance).where(
                WorkflowInstance.fdr_id==fdr.id).order_by(WorkflowInstance.execution_version))).all())
            assert document.doc_type=='fdr_scan'
            assert len(workflows)==2
            assert workflows[-1].execution_version==2
            assert workflows[-1].execution_state=='not_started'
            assert workflows[-1].lifecycle_state=='extraction_pending'
            assert await session.scalar(select(OutboxEvent.id).where(
                OutboxEvent.event_type=='WORKFLOW_WAKE',
                OutboxEvent.aggregate_id==str(workflows[-1].id)))
        await engine.dispose()
    asyncio.run(run())


def test_verification_report_exposes_safe_ocr_workflow_diagnostics():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            inst=Institution(aicte_id='P15-OCR-DIAGNOSTIC',name='OCR Diagnostic College',state='Delhi',
                head_name='P',contact_email='ocr-diagnostic@example.test',contact_phone='9000000014',status='active')
            session.add(inst);await session.flush()
            fdr=FDR(institution_id=inst.id,fdr_number='P15-OCR-DIAGNOSTIC-1',bank_name='AXIS BANK',branch='Main',
                amount=100,issue_date=date.today()-timedelta(days=10),maturity_date=date.today()+timedelta(days=365),
                status='submitted',lifecycle_state='validation_failed',execution_state='failed',
                authorization_state='not_required',trust_badge='self_declared',declared_data={},is_synthetic=False)
            session.add(fdr);await session.flush()
            workflow=WorkflowInstance(fdr_id=fdr.id,institution_id=inst.id,workflow_version='fdr-case-v1',
                execution_version=2,lifecycle_state='validation_failed',execution_state='failed',
                authorization_state='not_required')
            session.add(workflow);await session.flush()
            session.add(WorkflowNodeExecution(workflow_instance_id=workflow.id,node_key='extract_document',
                attempt=1,status='failed',error_class='TRANSIENT',error_code='TransientFailure',
                error_message='private provider detail must not be exposed',workflow_version='fdr-case-v1'))
            await session.commit()

            report=await get_report(session,fdr.id)
            assert report['processing']=={
                'execution_state':'failed',
                'current_node':None,
                'last_node':'extract_document',
                'last_node_status':'failed',
                'last_error_code':'TransientFailure',
                'extraction_status':'failed',
                'extraction_error_code':'TransientFailure',
                'extraction_confidence':None,
            }
            assert 'private provider detail' not in str(report)
        await engine.dispose()
    asyncio.run(run())


def test_mismatch_pipeline_creates_one_correction_notification(monkeypatch):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        from app.workers import tasks_workflow
        from app.integrations import storage_client
        from app.services import ocr_service,bank_verification_service
        from app.schemas.verification import OcrResult,BankVerifyResponse
        async with factory() as session:
            inst=Institution(aicte_id='P15-MISMATCH',name='Mismatch College',state='Delhi',head_name='P',
                contact_email='mismatch@example.test',contact_phone='9000000013',status='active')
            session.add(inst);await session.flush()
            actor=User(email='mismatch-user@example.test',full_name='Institution User',password_hash='x',
                role='institution',institution_id=inst.id,status='active',is_active=True)
            session.add(actor);await session.flush()
            today=date.today()
            fdr=FDR(institution_id=inst.id,fdr_number='P15-MISMATCH-1',bank_name='SBI',branch='Main',amount=100,
                issue_date=today-timedelta(days=20),maturity_date=today+timedelta(days=300),status='submitted',
                lifecycle_state='submitted',execution_state='not_started',authorization_state='not_required',
                verification_level='declared',trust_badge='self_declared',declared_data={'fdr_number':'P15-MISMATCH-1',
                    'bank_name':'SBI','branch':'Main','amount':100,'issue_date':(today-timedelta(days=20)).isoformat(),
                    'maturity_date':(today+timedelta(days=300)).isoformat(),'holder':'Mismatch College'},is_synthetic=False)
            session.add(fdr);await session.flush()
            doc=Document(fdr_id=fdr.id,doc_type='fdr_scan',s3_key='mismatch.pdf',content_type='application/pdf',uploaded_by=actor.id,version_no=1)
            session.add(doc);await session.flush()
            wf=WorkflowInstance(fdr_id=fdr.id,institution_id=inst.id,workflow_version='fdr-case-v1',execution_version=1,
                lifecycle_state='submitted',execution_state='not_started',authorization_state='not_required')
            session.add(wf);await session.commit()
        async def fake_ocr(*args,**kwargs):
            today=date.today()
            return OcrResult(fdr_number='P15-MISMATCH-1',bank_name='SBI',holder_name='Mismatch College',amount=Decimal('200'),
                issue_date=today-timedelta(days=20),maturity_date=today+timedelta(days=300),confidence=1)
        async def fake_bank(*args): return BankVerifyResponse(found=False)
        monkeypatch.setattr(tasks_workflow,'SessionLocal',factory)
        monkeypatch.setattr(storage_client,'get',lambda key:b'%PDF-mismatch')
        monkeypatch.setattr(ocr_service,'extract_fdr_fields',fake_ocr)
        monkeypatch.setattr(bank_verification_service,'verify_with_bank',fake_bank)
        await tasks_workflow._process_workflow(wf.id)
        await tasks_workflow._process_workflow(wf.id)  # duplicate worker delivery while waiting
        async with factory() as session:
            assert await session.scalar(select(func.count(Notification.id)).where(Notification.fdr_id==fdr.id))==1
            assert await session.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.event_type=='DELIVER_NOTIFICATION'))==1
            assert await session.scalar(select(func.count(CorrectionRequest.id)).where(CorrectionRequest.fdr_id==fdr.id))==1
        await engine.dispose()
    asyncio.run(run())
