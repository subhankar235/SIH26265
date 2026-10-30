import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.workflows import get_workflow, workflow_control_room_page, workflow_control_room_summary
from app.core.database import Base
from app.core.enums import FDRStatus, TrustBadge
from app.models import FDR, Institution
from app.models.workflow import WorkflowInstance


def test_control_room_uses_cursor_pagination_and_reports_missing_workflows():
    async def run():
        engine = create_async_engine(
            'sqlite+aiosqlite:///:memory:',
            poolclass=StaticPool,
            connect_args={'check_same_thread': False},
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with factory() as session:
            institution = Institution(
                aicte_id='AICTE-CONTROL-ROOM-001',
                name='Control Room College',
                state='Gujarat',
                head_name='Principal',
                contact_email='control-room@example.test',
                contact_phone='9000000003',
                status='active',
            )
            session.add(institution)
            await session.flush()
            fdrs = []
            for index in range(3):
                fdr = FDR(
                    institution_id=institution.id,
                    fdr_number=f'CONTROL-{index + 1}',
                    bank_name='SBI',
                    branch='Main',
                    amount=500000,
                    issue_date=date.today() - timedelta(days=30),
                    maturity_date=date.today() + timedelta(days=30),
                    status=FDRStatus.MISMATCH.value,
                    trust_badge=TrustBadge.MISMATCH.value,
                    declared_data={'fdr_number': f'CONTROL-{index + 1}'},
                )
                session.add(fdr)
                fdrs.append(fdr)
            await session.flush()
            session.add_all([
                WorkflowInstance(
                    fdr_id=fdrs[0].id,
                    institution_id=institution.id,
                    lifecycle_state='submitted',
                    execution_state='running',
                    authorization_state='pending',
                ),
                WorkflowInstance(
                    fdr_id=fdrs[1].id,
                    institution_id=institution.id,
                    lifecycle_state='submitted',
                    execution_state='blocked',
                    authorization_state='pending',
                ),
            ])
            await session.commit()

            official = SimpleNamespace(role='aicte_official')
            first_page = await workflow_control_room_page(
                before_id=None,
                page_size=1,
                execution_state=None,
                session=session,
                user=official,
            )
            second_page = await workflow_control_room_page(
                before_id=first_page['next_before_id'],
                page_size=1,
                execution_state=None,
                session=session,
                user=official,
            )
            summary = await workflow_control_room_summary(session=session, user=official)
            execution_detail=await get_workflow(workflow_id=first_page['items'][0]['id'],
                session=session,user=official)

            assert len(first_page['items']) == 1
            assert first_page['has_more'] is True
            assert second_page['items'][0]['id'] < first_page['items'][0]['id']
            assert second_page['has_more'] is False
            assert execution_detail['definition']['editable'] is False
            assert [node['key'] for node in execution_detail['definition']['nodes']]==[
                'extract_document','validate_fields','route_case']
            assert execution_detail['worker_busy'] is False
            assert summary == {
                'total_workflows': 2,
                'total_fdrs': 3,
                'fdrs_without_workflow': 1,
                'execution_state_counts': {
                    'not_started': 0,
                    'running': 1,
                    'waiting_event': 0,
                    'waiting_timer': 0,
                    'waiting_human': 0,
                    'paused': 0,
                    'retrying': 0,
                    'failed': 0,
                    'blocked': 1,
                    'cancelled': 0,
                    'completed': 0,
                },
            }
        await engine.dispose()

    asyncio.run(run())
