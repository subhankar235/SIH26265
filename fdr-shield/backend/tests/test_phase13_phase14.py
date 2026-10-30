import asyncio
from datetime import date, timedelta, datetime, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import RateLimitError
from app.core.exceptions import InvalidStateTransition
from app.models import FDR, Institution, User
from app.models.audit_log import AuditLog
from app.models.ml import MLDemoSample
from app.services.audit_service import record, verify_audit_chain
from app.services.ml_service import assess_gates, generate_synthetic_demo_data, list_registry, run_fallback_predictions
from app.services.rate_limit_service import enforce_rate_limit


def test_gate_zero_excludes_labeled_synthetic_data():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            admin=User(email='ml-admin@example.test',full_name='ML Admin',password_hash='x',
                role='admin',status='active',is_active=True)
            inst=Institution(aicte_id='ML-SYNTH-1',name='Demo Institution',state='Demo',head_name='Demo',
                contact_email='demo@example.test',contact_phone='9000000099',status='active')
            session.add_all([admin,inst]);await session.flush()
            session.add(FDR(institution_id=inst.id,fdr_number='SYNTHETIC-ML-1',bank_name='DEMO',branch='',amount=10,
                issue_date=date.today(),maturity_date=date.today()+timedelta(days=365),status='submitted',
                trust_badge='self_declared',declared_data={},is_synthetic=True))
            await session.flush()
            before=await assess_gates(session)
            assert all(g['real_rows']==0 for g in before['gates'])
            assert all(g['gate_status']=='BLOCKED_INSUFFICIENT_REAL_DATA' for g in before['gates'])
            assert next(g for g in before['gates'] if g['use_case']=='institution_dagmm')['synthetic_rows_excluded']==1
            generated=await generate_synthetic_demo_data(session,admin,count=3,seed=7)
            assert generated['total_rows']==9 and generated['is_synthetic'] is True
            after=await assess_gates(session)
            assert all(g['real_rows']==0 for g in after['gates'])
            institution=next(g for g in after['gates'] if g['use_case']=='institution_dagmm')
            assert institution['synthetic_rows_excluded']==4
            registry=await list_registry(session)
            assert len(registry)==3 and all(row['is_synthetic'] is True for row in registry)
            first_batch=list((await session.scalars(select(MLDemoSample).where(MLDemoSample.batch_id==generated['batch_id'],
                MLDemoSample.use_case=='institution_dagmm').order_by(MLDemoSample.sample_index))).all())
            second=await generate_synthetic_demo_data(session,admin,count=3,seed=7)
            second_batch=list((await session.scalars(select(MLDemoSample).where(MLDemoSample.batch_id==second['batch_id'],
                MLDemoSample.use_case=='institution_dagmm').order_by(MLDemoSample.sample_index))).all())
            assert [sample.features for sample in first_batch]==[sample.features for sample in second_batch]
        await engine.dispose()
    asyncio.run(run())


def test_audit_chain_detects_tampering_and_database_rejects_mutation():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            await record(session,None,'test_entity',1,'CREATED','127.0.0.1',{'value':[None,'one']})
            await record(session,None,'test_entity',1,'UPDATED','127.0.0.1',{'value':['one','two']})
            await session.commit()
            report=await verify_audit_chain(session)
            assert report['valid'] and report['record_count']==2
            with pytest.raises(IntegrityError):
                await session.execute(update(AuditLog).values(action='TAMPERED'))
            await session.rollback()
            assert (await verify_audit_chain(session))['valid']
        await engine.dispose()
    asyncio.run(run())


def test_institution_recommendations_respect_institution_scope_and_are_advisory():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            a=Institution(aicte_id='ML-REAL-A',name='A',state='Delhi',head_name='A',contact_email='a@x.test',contact_phone='9000000001',status='active')
            b=Institution(aicte_id='ML-REAL-B',name='B',state='Delhi',head_name='B',contact_email='b@x.test',contact_phone='9000000002',status='active')
            session.add_all([a,b]);await session.flush()
            own=FDR(institution_id=a.id,fdr_number='OWN-1',bank_name='SBI',branch='',amount=100,
                issue_date=date.today()-timedelta(days=10),maturity_date=date.today()+timedelta(days=4000),
                status='submitted',trust_badge='self_declared',declared_data={},ocr_data={},is_synthetic=False)
            other=FDR(institution_id=b.id,fdr_number='SECRET-2',bank_name='PNB',branch='',amount=100,
                issue_date=date.today(),maturity_date=date.today()+timedelta(days=365),status='submitted',
                trust_badge='self_declared',declared_data={},ocr_data={},is_synthetic=False)
            session.add_all([own,other]);await session.flush()
            admin=User(email='fallback-admin@example.test',full_name='Fallback Admin',password_hash='x',
                role='admin',status='active',is_active=True)
            session.add(admin);await session.flush()
            from app.services.ml_service import institution_recommendations
            result=await institution_recommendations(session,a.id)
            assert [r['fdr_id'] for r in result['recommendations']]==[own.id]
            assert result['recommendations'][0]['recommendation']=='unusual pattern — review suggested'
            assert result['recommendations'][0]['details']['authorization_effect']=='none'
            assert all('SECRET-2' not in str(row) for row in result['recommendations'])
            first=await run_fallback_predictions(session,admin,'institution_dagmm',100,'phase14-ml-key-123')
            duplicate=await run_fallback_predictions(session,admin,'institution_dagmm',100,'phase14-ml-key-123')
            assert first['count']==1 and duplicate['count']==0 and duplicate['duplicate'] is True
        await engine.dispose()
    asyncio.run(run())


def test_expensive_endpoint_rate_limiter_enforces_worker_fallback(monkeypatch):
    import redis
    class BrokenRedis:
        @staticmethod
        def from_url(*args,**kwargs): return BrokenRedis()
        def eval(self,*args,**kwargs): raise ConnectionError('unavailable')
        def close(self): pass
    monkeypatch.setattr(redis.Redis,'from_url',BrokenRedis.from_url)
    identity=f'phase14-test-{datetime.now(timezone.utc).timestamp()}'
    async def run():
        await enforce_rate_limit('test-scope',identity,1,60)
        with pytest.raises(RateLimitError):
            await enforce_rate_limit('test-scope',identity,1,60)
    asyncio.run(run())


def test_configured_upload_scanner_rejects_found_and_fails_closed(monkeypatch):
    from types import SimpleNamespace
    from app.integrations import upload_scanner
    monkeypatch.setattr(upload_scanner,'get_settings',lambda:SimpleNamespace(clamav_host='clamav',clamav_port=3310,clamav_timeout_seconds=1))
    monkeypatch.setattr(upload_scanner.asyncio,'to_thread',lambda fn,*args,**kwargs: asyncio.sleep(0,result='stream: Eicar FOUND'))
    with pytest.raises(InvalidStateTransition,match='MALWARE_DETECTED'):
        asyncio.run(upload_scanner.scan_upload(b'virus'))
    async def unavailable(*args,**kwargs): raise OSError('daemon offline')
    monkeypatch.setattr(upload_scanner.asyncio,'to_thread',unavailable)
    with pytest.raises(InvalidStateTransition,match='UPLOAD_SCANNER_UNAVAILABLE'):
        asyncio.run(upload_scanner.scan_upload(b'clean'))
