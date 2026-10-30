import asyncio
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.deps import Pagination
from app.models.discrepancy import Discrepancy
from app.models.fdr import FDR
from app.models.institution import Institution
from app.models.workflow import WorkflowInstance, WorkflowNodeExecution
from app.services.verification_service import get_report, list_discrepancies


def test_showcase_findings_are_real_origin_scoped_and_use_recorded_detection_time():
    async def scenario():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        detected = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)
        async with factory() as session:
            institution = Institution(aicte_id='A-1', name='Test College', state='Delhi',
                head_name='Registrar', contact_email='test@example.invalid', contact_phone='1234567890')
            session.add(institution)
            await session.flush()
            real = FDR(institution_id=institution.id, fdr_number='REAL-1', bank_name='SBI', branch='Central',
                amount=100000, issue_date=date(2025, 1, 1), maturity_date=date(2027, 1, 1),
                status='MISMATCH', lifecycle_state='under_review', execution_state='completed',
                trust_badge='mismatch', declared_data={}, ocr_data={}, is_synthetic=False)
            demo = FDR(institution_id=institution.id, fdr_number='DEMO-1', bank_name='SBI', branch='Central',
                amount=100000, issue_date=date(2025, 1, 1), maturity_date=date(2027, 1, 1),
                status='MISMATCH', lifecycle_state='under_review', execution_state='completed',
                trust_badge='mismatch', declared_data={}, ocr_data={}, is_synthetic=True)
            session.add_all([real, demo])
            await session.flush()
            workflow = WorkflowInstance(fdr_id=real.id, institution_id=institution.id,
                lifecycle_state='under_review', execution_state='completed', authorization_state='pending',
                workflow_version='fdr-case-v1', execution_version=1)
            session.add(workflow)
            await session.flush()
            session.add(WorkflowNodeExecution(workflow_instance_id=workflow.id, node_key='validate_fields',
                attempt=1, status='succeeded', workflow_version='fdr-case-v1',
                output_ref={'review_assessment': {'assessment': 'additional_review',
                    'summary': 'Additional review is suggested.', 'provider': 'hidden-internal',
                    'model_version': 'private-version'}}))
            session.add_all([
                Discrepancy(fdr_id=real.id, field='amount', declared_value='100000', extracted_value='90000',
                    source='ocr', severity='high', resolved=False, detected_at=detected),
                Discrepancy(fdr_id=demo.id, field='amount', declared_value='100000', extracted_value='90000',
                    source='ocr', severity='high', resolved=False, detected_at=detected),
            ])
            await session.flush()
            rows = await list_discrepancies(session, False, Pagination(), real_only=True)
            assert len(rows['items']) == 1
            assert rows['items'][0]['fdr_number'] == 'REAL-1'
            assert rows['items'][0]['institution_name'] == 'Test College'
            assert rows['items'][0]['detected_at'].replace(tzinfo=timezone.utc) == detected
            assert rows['has_more'] is False
            official_report = await get_report(session, real.id, include_review_assessment=True)
            assert official_report['review_assessment'] == {
                'assessment': 'additional_review', 'summary': 'Additional review is suggested.'}
            institution_report = await get_report(session, real.id, institution_id=institution.id)
            assert institution_report['review_assessment'] is None
        await engine.dispose()

    asyncio.run(scenario())
