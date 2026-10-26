import asyncio
from datetime import date, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.enums import AuthorizationState, ExecutionState, FDRStatus, LifecycleState, VerificationLevel, TrustBadge
from app.models import Document, FDR, Institution
from app.models.workflow import WorkflowEvent, WorkflowInstance
from scripts import backfill_workflows


def test_workflow_backfill_is_resumable_and_versions_existing_documents(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool,
            connect_args={'check_same_thread': False})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution = Institution(aicte_id='AICTE-BACKFILL-001', name='Legacy College', state='Gujarat',
                head_name='Principal', contact_email='legacy@example.test', contact_phone='9000000002', status='active')
            session.add(institution); await session.flush()
            fdr = FDR(institution_id=institution.id, fdr_number='LEGACY-001', bank_name='SBI', branch='Main',
                amount=500000, issue_date=date.today()-timedelta(days=365), maturity_date=date.today()+timedelta(days=20),
                status=FDRStatus.MISMATCH.value, trust_badge=TrustBadge.MISMATCH.value,
                declared_data={'fdr_number':'LEGACY-001'}, ocr_data={'fdr_number':'LEGACY-001'},
                bank_data={'found':True, 'status':'ACTIVE'})
            session.add(fdr); await session.flush()
            session.add_all([
                Document(fdr_id=fdr.id, doc_type='fdr_scan', s3_key='legacy/v1.pdf', content_type='application/pdf', uploaded_by=1),
                Document(fdr_id=fdr.id, doc_type='fdr_scan', s3_key='legacy/v2.pdf', content_type='application/pdf', uploaded_by=1),
            ])
            await session.commit()
        monkeypatch.setattr(backfill_workflows, 'SessionLocal', factory)
        await backfill_workflows.backfill()
        await backfill_workflows.backfill()
        async with factory() as session:
            instance = await session.scalar(select(WorkflowInstance).where(WorkflowInstance.fdr_id == fdr.id))
            assert instance.lifecycle_state == LifecycleState.CORRECTION_REQUIRED.value
            assert instance.execution_state == ExecutionState.NOT_STARTED.value
            assert instance.authorization_state == AuthorizationState.PENDING.value
            assert await session.scalar(select(func.count(WorkflowEvent.id)).where(WorkflowEvent.workflow_instance_id == instance.id)) == 1
            refreshed_fdr = await session.get(FDR, fdr.id)
            assert refreshed_fdr.verification_level == VerificationLevel.MOCK_VERIFIED.value
            docs = list((await session.scalars(select(Document).where(Document.fdr_id == fdr.id).order_by(Document.id))).all())
            assert [doc.version_no for doc in docs] == [1, 2]
            assert docs[1].supersedes_document_id == docs[0].id
        await engine.dispose()
    asyncio.run(run())
