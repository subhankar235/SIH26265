import asyncio
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
from sqlalchemy.pool import StaticPool
import pytest
from app.core.database import Base
from app.core.enums import Role,ExecutionState,LifecycleState,AuthorizationState
from app.core.exceptions import InvalidStateTransition,NotFound,PermissionDenied
from app.models import Discrepancy,FDR,Institution,User
from app.models.workflow import CommandExecution,ExceptionItem,OutboxEvent,WorkflowInstance
from app.services.command_service import interpret,confirm,_interpret_text
from app.services.command_service import _registered_tool_catalog


def test_command_interpreter_allowlists_intents_scopes_case_refs_and_confirms_writes():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            one=Institution(aicte_id='AICTE-CMD-1',name='North College',state='Delhi',head_name='P1',
                contact_email='north@example.test',contact_phone='9000000011',status='active')
            two=Institution(aicte_id='AICTE-CMD-2',name='South College',state='Tamil Nadu',head_name='P2',
                contact_email='south@example.test',contact_phone='9000000012',status='active')
            session.add_all([one,two]);await session.flush()
            institution_user=User(email='north-user@example.test',full_name='North User',password_hash='x',
                role=Role.INSTITUTION.value,institution_id=one.id,status='active',is_active=True)
            official=User(email='cmd-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            admin=User(email='cmd-admin@example.test',full_name='Admin',password_hash='x',
                role=Role.ADMIN.value,status='active',is_active=True)
            session.add_all([institution_user,official,admin]);await session.flush()
            fdr=FDR(institution_id=two.id,fdr_number='FDR-1024',bank_name='SBI',branch='Main',amount=100,
                issue_date=date.today(),maturity_date=date.today()+timedelta(days=20),status='submitted',
                trust_badge='self_declared',declared_data={})
            session.add(fdr);await session.flush()
            wf=WorkflowInstance(fdr_id=fdr.id,institution_id=two.id,workflow_version='v1',execution_version=1,
                lifecycle_state=LifecycleState.SUBMITTED.value,execution_state=ExecutionState.NOT_STARTED.value,
                authorization_state=AuthorizationState.NOT_REQUIRED.value)
            session.add(wf);await session.commit()
            with pytest.raises(NotFound):
                await interpret(session,institution_user,'Explain why FDR-1024 is blocked','institution-cmd-key-1')
            with pytest.raises(InvalidStateTransition,match='Bulk release/refund approvals are unsupported'):
                await interpret(session,official,'Approve release for all FDRs','official-cmd-key-1')
            read_command,plan=await interpret(session,official,'Find FDRs maturing within 30 days','official-cmd-key-2')
            assert plan['intent']=='find_maturing' and plan['resolved_targets'][0]['fdr_number']=='FDR-1024'
            assert read_command.requires_confirmation is False
            assert await session.scalar(select(OutboxEvent.id).where(OutboxEvent.event_type=='COMMAND_EXECUTE'))
            admin_read,_=await interpret(session,admin,'Find FDRs maturing within 30 days','admin-cmd-key-1')
            assert admin_read.requires_confirmation is False
            with pytest.raises(PermissionDenied,match='read-only'):
                await interpret(session,admin,'Prepare reminder drafts','admin-cmd-key-2')
            command,plan=await interpret(session,official,'Pause FDR-1024','official-cmd-key-3')
            assert command.requires_confirmation and command.status=='planned'
            with pytest.raises(NotFound):
                await confirm(session,admin,command.id,command.plan_hash)
            fdr.status='verified'
            with pytest.raises(InvalidStateTransition,match='PLAN_CHANGED'):
                await confirm(session,official,command.id,command.plan_hash)
        await engine.dispose()
    asyncio.run(run())


def test_fdr_count_question_uses_authorized_database_count():
    from app.services.command_service import _parse_offline
    from app.services.command_tools import (
        CountFdrsArgs, ListRecentFdrsArgs, execute_count_fdrs,
        execute_list_recent_fdrs, preview_count_fdrs, preview_list_recent_fdrs,
    )
    from app.services.llm_service import grounded_fallback

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            one=Institution(aicte_id='AICTE-CMD-COUNT-1',name='Count College One',state='Delhi',
                head_name='Principal',contact_email='count-one@example.test',
                contact_phone='9000000031',status='active')
            two=Institution(aicte_id='AICTE-CMD-COUNT-2',name='Count College Two',state='Punjab',
                head_name='Principal',contact_email='count-two@example.test',
                contact_phone='9000000032',status='active')
            session.add_all([one,two]);await session.flush()
            official=User(email='count-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            institution_user=User(email='count-user@example.test',full_name='Institution User',password_hash='x',
                role=Role.INSTITUTION.value,institution_id=one.id,status='active',is_active=True)
            session.add_all([official,institution_user])
            for index,institution in enumerate((one,one,two),1):
                session.add(FDR(institution_id=institution.id,fdr_number=f'COUNT-{index}',
                    bank_name='SBI',branch='Main',amount=1000,issue_date=date.today(),
                    maturity_date=date.today()+timedelta(days=30),status='submitted',
                    trust_badge='self_declared',declared_data={}))
            await session.flush()

            assert _parse_offline('how many total fdr r there check and tell') == {
                'intent':'COUNT_FDRS','args':{},
            }
            assert _parse_offline('count the fixed deposit records') == {
                'intent':'COUNT_FDRS','args':{},
            }
            assert _parse_offline('Pause FDR-COUNT-1') == {
                'intent':'PAUSE_CASE','args':{'fdr_ref':'FDR-COUNT-1'},
            }
            assert _parse_offline('hey give me summary abt last 2 fdrs') == {
                'intent':'LIST_RECENT_FDRS','args':{'limit':2},
            }
            assert _parse_offline('tell me about last five FDRs') == {
                'intent':'LIST_RECENT_FDRS','args':{'limit':5},
            }
            assert await preview_count_fdrs(session,official,CountFdrsArgs()) == {
                'targets':[],'snapshot':[],
                'effect_summary':'Count all FDR records visible to this user in the portal: 3.',
                'warnings':[],'result_metadata':{'total_fdrs':3},
            }
            result=await execute_count_fdrs(session,institution_user,CountFdrsArgs(),{},None)
            assert result=={'total_fdrs':2}
            recent_official = await preview_list_recent_fdrs(
                session,official,ListRecentFdrsArgs(limit=2)
            )
            assert [item['fdr_number'] for item in recent_official['targets']] == [
                'COUNT-3','COUNT-2',
            ]
            recent_institution = await preview_list_recent_fdrs(
                session,institution_user,ListRecentFdrsArgs(limit=5)
            )
            assert [item['fdr_number'] for item in recent_institution['targets']] == [
                'COUNT-2','COUNT-1',
            ]
            assert 'COUNT-3' not in grounded_fallback('list_recent_fdrs', {
                'records': recent_institution['targets'],
            })
            recent_command, recent_plan = await interpret(
                session,institution_user,'hey give me summary abt last 2 fdrs',
                'recent-fdr-institution-read-1',
            )
            assert recent_command is not None
            assert recent_plan['tool'] == 'list_recent_fdrs'
            assert recent_plan['args'] == {'limit': 2}
            actual_result = await execute_list_recent_fdrs(
                session,institution_user,ListRecentFdrsArgs(limit=2),recent_plan,None
            )
            assert actual_result['count'] == 2
            assert [record['fdr_number'] for record in actual_result['records']] == [
                'COUNT-2','COUNT-1',
            ]
            institution_count, count_plan = await interpret(
                session,institution_user,'how many total FDRs are there','count-institution-api-read-1'
            )
            assert institution_count is not None
            assert count_plan['result_metadata']['total_fdrs'] == 2
            with pytest.raises(PermissionDenied):
                await interpret(session,institution_user,'Pause FDR-COUNT-1','count-institution-write-denied')
        await engine.dispose()
    asyncio.run(run())


def test_command_interpreter_uses_configured_llm_and_parses_structured_intent(monkeypatch):
    from types import SimpleNamespace
    import app.services.command_service as service

    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices': [{'message': {'content': '{"intent":"FIND_MATURING","args":{"days":45},"confidence":0.99}'}}]}

    class Client:
        def __init__(self, timeout): assert timeout == 3
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json, headers):
            assert url == 'http://ollama/v1/chat/completions'
            assert json['model'] == 'qwen2.5:3b'
            assert headers['Authorization'] == 'Bearer test-token'
            assert 'response_format' not in json
            assert '"find_maturing"' in json['messages'][0]['content']
            assert '<user_command>' in json['messages'][1]['content']
            return Response()

    monkeypatch.setattr(service, 'get_settings', lambda: SimpleNamespace(
        command_llm_enabled=True,
        command_llm_api_url='http://ollama/v1/chat/completions',
        command_llm_api_key='test-token',
        ollama_api_key='ocr-only-token',
        command_llm_model='qwen2.5:3b',
        command_llm_timeout=3,
    ))
    monkeypatch.setattr(service.httpx, 'AsyncClient', Client)
    parsed, interpreter = asyncio.run(_interpret_text('Find FDRs maturing in 45 days'))
    assert parsed.intent == 'find_maturing'
    assert parsed.args == {'days': 45}
    assert interpreter == 'llm-structured'


def test_llm_tool_catalog_is_built_from_registered_tools_and_role_permissions():
    official={item['tool'] for item in _registered_tool_catalog(Role.AICTE_OFFICIAL.value)}
    admin_catalog=_registered_tool_catalog(Role.ADMIN.value)
    admin={item['tool'] for item in admin_catalog}
    institution={item['tool'] for item in _registered_tool_catalog(Role.INSTITUTION.value)}
    assert {'get_fdr_details','list_unresolved_discrepancies','analyze_maturing_discrepancies',
        'get_task_status','recheck_document'} <= official
    assert 'recheck_document' not in admin
    assert all(item['kind']=='read' and not item['confirmation_required'] for item in admin_catalog)
    assert 'get_fdr_details' in institution and 'recheck_document' not in institution


def test_ollama_command_response_fences_and_common_intent_aliases_are_normalized(monkeypatch):
    from types import SimpleNamespace
    import app.services.command_service as service

    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices':[{'message':{'content':'```json\n{"action":"filter_fixed_deposits",'
                '"parameters":{"maturity_window_days":45}}\n```'}}]}

    class Client:
        def __init__(self,timeout): assert timeout==5
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): return Response()

    monkeypatch.setattr(service,'get_settings',lambda:SimpleNamespace(command_llm_enabled=True,
        command_llm_api_url='https://ollama.test/v1/chat/completions',command_llm_api_key='test-key',
        command_llm_model='gemma4:31b',command_llm_timeout=5))
    monkeypatch.setattr(service.httpx,'AsyncClient',Client)
    parsed,source=asyncio.run(service._interpret_text('Find FDRs maturing within 45 days'))
    assert parsed.intent=='find_maturing' and parsed.args=={'days':45}
    assert source=='llm-structured'


def test_command_interpreter_falls_back_when_llm_is_unconfigured_or_offline(monkeypatch):
    from types import SimpleNamespace
    import httpx
    import app.services.command_service as service

    configured = SimpleNamespace(command_llm_enabled=True, command_llm_api_url='',
        command_llm_api_key='', command_llm_model='', command_llm_timeout=1)
    monkeypatch.setattr(service, 'get_settings', lambda: configured)
    parsed, interpreter = asyncio.run(_interpret_text('Find FDRs maturing in 45 days'))
    assert parsed.intent == 'find_maturing' and interpreter == 'deterministic-allowlist-v1'

    configured.command_llm_api_url = 'http://unavailable/v1/chat/completions'
    configured.command_llm_model = 'model'

    class Client:
        def __init__(self, timeout): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise httpx.ConnectError('provider offline')

    monkeypatch.setattr(service.httpx, 'AsyncClient', Client)
    parsed, interpreter = asyncio.run(_interpret_text('Find FDRs maturing in 45 days'))
    assert parsed.args == {'days': 45} and interpreter == 'deterministic-allowlist-v1'


def test_local_eager_command_runs_without_celery_or_beat(monkeypatch):
    from types import SimpleNamespace
    from app.models.workflow import CommandExecution
    from app.services import command_service, local_execution_service
    import app.services.llm_service as llm_service

    class LocalBus:
        async def broadcast(self,*args,**kwargs): return None

    async def grounded_answer(question, tool_name, result, fallback, conversation=None):
        assert question == 'Find FDRs maturing in 30 days'
        assert tool_name == 'find_fdrs'
        assert result == {'found': 0, 'returned_count': 0, 'truncated': False, 'results': []}
        assert 'No FDR records matched' in fallback
        return 'No FDRs match that maturity window.', 'llm-grounded'

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(local_execution_service,'get_settings',
            lambda:SimpleNamespace(celery_task_always_eager=True))
        monkeypatch.setattr(command_service,'get_event_bus',lambda:LocalBus())
        monkeypatch.setattr(llm_service,'generate_grounded_reply_with_source',grounded_answer)
        async with factory() as session:
            official=User(email='inline-cmd@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(official);await session.flush()
            command=CommandExecution(user_id=official.id,raw_command='Find FDRs maturing in 30 days',
                idempotency_key='inline-command-123',interpreted_plan={'tool':'find_fdrs',
                    'intent':'find_maturing','args':{'days':30},'resolved_targets':[],'state_snapshot':[]},
                plan_hash='a'*64,authorization_result={'allowed':True,'role':official.role},
                requires_confirmation=False,status='confirmed',steps=[])
            session.add(command);await session.flush()
            wake=OutboxEvent(aggregate_id=str(command.id),event_type='COMMAND_EXECUTE',
                payload={'command_id':command.id},idempotency_key='inline-command-wake-123',status='pending')
            session.add(wake);await session.commit()

            assert await local_execution_service.run_inline_command_if_enabled(session,command.id)
            await session.refresh(command);await session.refresh(wake)
            assert command.status=='succeeded'
            assert wake.status=='sent'
            assert command.result_summary=='No FDRs match that maturity window.'
            assert command.steps[0]['result']=={
                'answer':'No FDRs match that maturity window.',
                'answer_source':'llm-grounded',
                'data':{'found':0,'returned_count':0,'truncated':False,'results':[]},
            }
        await engine.dispose()
    asyncio.run(run())


def test_fdr_details_question_uses_authorized_database_records():
    from app.models.discrepancy import Discrepancy
    from app.models.workflow import VerificationRun
    from app.services.command_tools import TOOLS
    from app.services.command_service import _parse_offline

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-CMD-DETAILS',name='Details College',state='Delhi',
                head_name='Principal',contact_email='details@example.test',contact_phone='9000000004',
                status='active')
            session.add(institution);await session.flush()
            actor=User(email='details-user@example.test',full_name='Institution User',password_hash='x',
                role=Role.INSTITUTION.value,institution_id=institution.id,status='active',is_active=True)
            session.add(actor);await session.flush()
            fdr=FDR(institution_id=institution.id,fdr_number='FDR-DETAILS-1',bank_name='SBI',
                branch='Main',amount=1000,issue_date=date.today(),maturity_date=date.today()+timedelta(days=5),
                status='mismatch',trust_badge='mismatch',declared_data={},
                verification_level='mock_verified',is_synthetic=True)
            session.add(fdr);await session.flush()
            session.add_all([
                Discrepancy(fdr_id=fdr.id,field='amount',declared_value='1000',
                    extracted_value='900',source='ocr',severity='high',resolved=False),
                Discrepancy(fdr_id=fdr.id,field='holder',declared_value='private name',
                    extracted_value='another name',source='ocr',severity='high',resolved=False),
                VerificationRun(fdr_id=fdr.id,extraction_engine='test-ocr',source='mock_bank',
                    verification_level='mock_verified',declared_snapshot={'amount':1000},
                    extracted_fields={'amount':900},discrepancies=[],confidence=0.9),
            ])
            await session.commit()

            parsed=_parse_offline('What discrepancies and details are recorded for FDR-DETAILS-1?')
            assert parsed=={'intent':'GET_FDR_DETAILS','args':{'fdr_ref':'FDR-DETAILS-1'}}
            result=await TOOLS['get_fdr_details'].execute(
                session,actor,TOOLS['get_fdr_details'].args_model.model_validate(parsed['args']),{},None
            )
            assert result['fdr']['fdr_number']=='FDR-DETAILS-1'
            assert result['fdr']['is_synthetic'] is True
            assert result['workflow'] is None
            assert result['unresolved_discrepancies']==[{
                'field':'amount','declared_value':'1000','observed_value':'900',
                'source':'ocr','severity':'high','resolved':False,
            }]
            assert result['verification_runs'][0]['source']=='mock_bank'
            assert 'private name' not in str(result)
            with pytest.raises(NotFound):
                await TOOLS['get_fdr_details'].execute(
                    session,User(role=Role.INSTITUTION.value,institution_id=999),
                    TOOLS['get_fdr_details'].args_model.model_validate({'fdr_ref':'FDR-DETAILS-1'}),{},None
                )
        await engine.dispose()
    asyncio.run(run())


def test_offline_parser_recognizes_bank_prefixed_fdr_reference_and_resolves_exact_match():
    from app.services.command_service import _parse_offline
    from app.services.command_tools import resolve_fdr_reference

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-CMD-REFS',name='Reference College',state='Delhi',
                head_name='Principal',contact_email='refs@example.test',contact_phone='9000000006',
                status='active')
            session.add(institution);await session.flush()
            actor=User(email='refs-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(actor)
            exact=FDR(institution_id=institution.id,fdr_number='HDFC0123456789',bank_name='HDFC',
                branch='Main',amount=1000,issue_date=date.today(),maturity_date=date.today()+timedelta(days=5),
                status='submitted',trust_badge='self_declared',declared_data={})
            formatted=FDR(institution_id=institution.id,fdr_number='HDFC-0123456789',bank_name='HDFC',
                branch='Other',amount=2000,issue_date=date.today(),maturity_date=date.today()+timedelta(days=6),
                status='submitted',trust_badge='self_declared',declared_data={})
            session.add_all([exact,formatted])
            await session.flush()

            parsed=_parse_offline("what's the details about HDFC0123456789")
            assert parsed=={'intent':'GET_FDR_DETAILS','args':{'fdr_ref':'HDFC0123456789'}}
            assert (await resolve_fdr_reference(session,actor,'HDFC0123456789')).id==exact.id
            assert (await resolve_fdr_reference(session,actor,'HDFC-0123456789')).id==formatted.id
            with pytest.raises(InvalidStateTransition,match='different formatting'):
                await resolve_fdr_reference(session,actor,'hdfc0123456789')
        await engine.dispose()
    asyncio.run(run())


def test_fdr_maturity_search_counts_database_matches_when_results_are_capped():
    from app.core.clock import business_today
    from app.services.command_tools import FindFdrsArgs, preview_find_fdrs

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-CMD-LARGE',name='Large Dataset College',state='Delhi',
                head_name='Principal',contact_email='large@example.test',contact_phone='9000000005',
                status='active')
            session.add(institution);await session.flush()
            session.add_all([
                FDR(institution_id=institution.id,fdr_number=f'FDR-LARGE-{index:03d}',
                    bank_name='SBI',branch='Main',amount=1000,issue_date=date.today(),
                    maturity_date=business_today()+timedelta(days=2),status='submitted',
                    trust_badge='self_declared',declared_data={})
                for index in range(201)
            ])
            await session.flush()
            official=User(email='large-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(official);await session.flush()

            preview=await preview_find_fdrs(session,official,FindFdrsArgs(days=10))
            assert len(preview['targets'])==200
            assert preview['result_metadata']=={
                'matched_total':201,'returned_count':200,'truncated':True,
            }
            assert 'first 200' in preview['warnings'][0]
        await engine.dispose()
    asyncio.run(run())


def test_composite_maturity_and_discrepancy_tool_uses_authorized_database_rows():
    from app.core.clock import business_today
    from app.services.command_tools import AnalyzeMaturingDiscrepanciesArgs,execute_analyze_maturing_discrepancies

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            first=Institution(aicte_id='AICTE-ANALYZE-A',name='A College',state='Delhi',head_name='A',
                contact_email='a@example.test',contact_phone='9000000061',status='active')
            second=Institution(aicte_id='AICTE-ANALYZE-B',name='B College',state='Delhi',head_name='B',
                contact_email='b@example.test',contact_phone='9000000062',status='active')
            session.add_all([first,second]);await session.flush()
            user=User(email='analyze-user@example.test',full_name='Institution User',password_hash='x',
                role=Role.INSTITUTION.value,institution_id=first.id,status='active',is_active=True)
            session.add(user);await session.flush()
            match=FDR(institution_id=first.id,fdr_number='ANALYZE-MATCH-1',bank_name='SBI',branch='Main',
                amount=1000,issue_date=business_today(),maturity_date=business_today()+timedelta(days=30),
                status='submitted',trust_badge='self_declared',declared_data={})
            other=FDR(institution_id=second.id,fdr_number='ANALYZE-OTHER-1',bank_name='HDFC',branch='Main',
                amount=1000,issue_date=business_today(),maturity_date=business_today()+timedelta(days=30),
                status='submitted',trust_badge='self_declared',declared_data={})
            session.add_all([match,other]);await session.flush()
            session.add(Discrepancy(fdr_id=match.id,field='amount',declared_value='1000',
                extracted_value='900',source='ocr',severity='high',resolved=False))
            session.add(Discrepancy(fdr_id=other.id,field='amount',declared_value='1000',
                extracted_value='900',source='ocr',severity='high',resolved=False))
            result=await execute_analyze_maturing_discrepancies(session,user,
                AnalyzeMaturingDiscrepanciesArgs(days=45,limit=20),{},None)
            assert result['matching_fdrs']==1
            assert result['records_with_discrepancies']==1
            assert result['records'][0]['fdr_number']=='ANALYZE-MATCH-1'
            assert result['records'][0]['unresolved_discrepancies'][0]['field']=='amount'
        await engine.dispose()
    asyncio.run(run())


def test_reminder_action_creates_real_recipient_drafts_without_sending_or_fake_addresses():
    from app.core.clock import business_today
    from app.services.command_tools import PrepareRemindersArgs,execute_prepare_reminders,preview_prepare_reminders
    from app.models.notification import Notification

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            inst=Institution(aicte_id='AICTE-DRAFT-1',name='Reminder College',state='Delhi',
                head_name='Principal',contact_email='actual-contact@example.test',contact_phone='9000000065',status='active')
            session.add(inst);await session.flush()
            actor=User(email='draft-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(actor);await session.flush()
            fdr=FDR(institution_id=inst.id,fdr_number='DRAFT-REAL-1',bank_name='SBI',branch='Main',
                amount=1000,issue_date=business_today(),maturity_date=business_today()+timedelta(days=10),
                status='submitted',trust_badge='self_declared',declared_data={})
            session.add(fdr);await session.flush()
            session.add(WorkflowInstance(fdr_id=fdr.id,institution_id=inst.id,workflow_version='v1',
                execution_version=1,lifecycle_state='renewal_required',execution_state='waiting_human',
                authorization_state='pending'))
            await session.flush()
            args=PrepareRemindersArgs(days=30)
            preview=await preview_prepare_reminders(session,actor,args)
            assert preview['targets'][0]['recipient']=='actual-contact@example.test'
            result=await execute_prepare_reminders(session,actor,args,{'resolved_targets':preview['targets']})
            assert result['drafts_prepared']==1
            assert result['drafts'][0]['recipient']=='actual-contact@example.test'
            assert result['drafts'][0]['status']=='draft_not_sent'
            assert await session.scalar(select(Notification.id)) is None
        await engine.dispose()
    asyncio.run(run())


def test_escalation_uses_authorized_exception_decision_service_and_persists_resolution():
    from app.services.command_tools import EscalateCasesArgs,execute_escalate_cases,preview_escalate_cases
    from app.models.workflow import WorkflowEvent

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            inst=Institution(aicte_id='AICTE-ESCALATE-1',name='Escalate College',state='Delhi',
                head_name='Principal',contact_email='escalate@example.test',contact_phone='9000000066',status='active')
            session.add(inst);await session.flush()
            actor=User(email='escalate-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(actor);await session.flush()
            fdr=FDR(institution_id=inst.id,fdr_number='ESCALATE-REAL-1',bank_name='SBI',branch='Main',
                amount=1000,issue_date=date.today(),maturity_date=date.today()+timedelta(days=20),
                status='mismatch',trust_badge='mismatch',declared_data={})
            session.add(fdr);await session.flush()
            wf=WorkflowInstance(fdr_id=fdr.id,institution_id=inst.id,workflow_version='v1',execution_version=1,
                lifecycle_state='correction_required',execution_state='waiting_event',authorization_state='pending')
            session.add(wf);await session.flush()
            exception=ExceptionItem(workflow_instance_id=wf.id,reason_code='HIGH_DISCREPANCY',priority=3,status='open')
            session.add(exception);await session.flush()
            args=EscalateCasesArgs(fdr_ref=fdr.fdr_number,reason='Escalate for senior review')
            preview=await preview_escalate_cases(session,actor,args)
            result=await execute_escalate_cases(session,actor,args,
                {'resolved_targets':preview['targets'],'_command_id':77})
            await session.flush()
            assert result['escalated_count']==1
            assert exception.status=='resolved'
            assert wf.lifecycle_state=='escalated'
            assert await session.scalar(select(WorkflowEvent.id).where(
                WorkflowEvent.event_type=='OFFICIAL_ESCALATED_EXCEPTION'))
        await engine.dispose()
    asyncio.run(run())


def test_unsupported_conversation_gets_chat_reply_instead_of_command_conflict(monkeypatch):
    import app.services.command_service as service
    import app.services.llm_service as llm_service

    async def unavailable_command_parser(_text,_context=None,_role=None):
        raise InvalidStateTransition('This command is not in the supported allowlist. No action was performed.')

    async def chat_reply(question, fallback, conversation=None):
        assert question == 'Hi, what can you help me with?'
        assert 'language model is unavailable' in fallback
        assert conversation == []
        return 'Hello! I can help with general FDR guidance.', 'llm-chat'

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(service,'_interpret_text',unavailable_command_parser)
        monkeypatch.setattr(llm_service,'generate_command_chat_reply',chat_reply)
        async with factory() as session:
            official=User(email='chat-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(official);await session.flush()
            command, response=await interpret(session,official,'Hi, what can you help me with?','chat-key-123456')
            assert command is None
            assert response=={'mode':'chat','reply':'Hello! I can help with general FDR guidance.',
                'interpreter':'llm-chat','conversation_id':None,'message_id':1}
            saved=await session.scalar(select(CommandExecution))
            assert saved is not None and saved.status=='succeeded'
            assert saved.result_summary=='Hello! I can help with general FDR guidance.'
        await engine.dispose()
    asyncio.run(run())


def test_persisted_chat_context_can_resolve_followup_then_run_real_scoped_tool(monkeypatch):
    import app.services.command_service as service
    import app.services.llm_service as llm_service
    from app.schemas.workflow import CommandIntentModel

    async def interpret_with_context(text,conversation=None,actor_role=None):
        assert actor_role==Role.AICTE_OFFICIAL.value
        if text=='Please help me understand FDR-CONTEXT-42':
            raise InvalidStateTransition('Not a supported direct action.')
        if text=='What is the status of that operation?':
            raise InvalidStateTransition('Provider could not classify the contextual follow-up.')
        assert text=='What discrepancies does it have?'
        assert any(item['role']=='user' and 'FDR-CONTEXT-42' in item['content'] for item in conversation)
        assert any(item['role']=='assistant' and 'not queried records' in item['content']
            for item in conversation)
        return CommandIntentModel(intent='get_fdr_details',args={'fdr_ref':'FDR-CONTEXT-42'},confidence=.97),'llm-structured'

    async def chat_reply(question,fallback,conversation=None):
        assert conversation==[]
        return 'I have not queried records yet. I can check that FDR when you ask for its details.','llm-chat'

    async def grounded_reply(question,tool_name,result,fallback,conversation=None):
        if tool_name=='get_task_status':
            assert result['status']=='succeeded'
            return 'The earlier query completed successfully.','llm-grounded'
        assert tool_name=='get_fdr_details'
        assert result['fdr']['fdr_number']=='FDR-CONTEXT-42'
        assert result['unresolved_discrepancies']
        assert any(item['role']=='assistant' for item in conversation)
        return 'FDR-CONTEXT-42 has one stored unresolved amount discrepancy.','llm-grounded'

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(service,'_interpret_text',interpret_with_context)
        monkeypatch.setattr(llm_service,'generate_command_chat_reply',chat_reply)
        monkeypatch.setattr(llm_service,'generate_grounded_reply_with_source',grounded_reply)
        async with factory() as session:
            institution=Institution(aicte_id='AICTE-CONTEXT-42',name='Context College',state='Delhi',
                head_name='Principal',contact_email='context@example.test',contact_phone='9000000042',status='active')
            session.add(institution);await session.flush()
            official=User(email='context-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(official);await session.flush()
            fdr=FDR(institution_id=institution.id,fdr_number='FDR-CONTEXT-42',bank_name='SBI',branch='Main',
                amount=1000,issue_date=date.today(),maturity_date=date.today()+timedelta(days=60),
                status='submitted',trust_badge='self_declared',verification_level='extracted',
                declared_data={'fdr_number':'FDR-CONTEXT-42'})
            session.add(fdr);await session.flush()
            session.add(Discrepancy(fdr_id=fdr.id,field='amount',declared_value='1000',
                extracted_value='1100',source='ocr',severity='high',resolved=False))
            workflow=WorkflowInstance(fdr_id=fdr.id,institution_id=institution.id,workflow_version='v1',
                execution_version=1,lifecycle_state='submitted',execution_state='waiting_human',
                authorization_state='pending')
            session.add(workflow);await session.commit()

            conversation_id='conversation-context-42'
            first,chat=await service.interpret(session,official,'Please help me understand FDR-CONTEXT-42',
                'context-chat-key-0001',conversation_id)
            assert first is None and chat['mode']=='chat'
            await session.commit()
            second,plan=await service.interpret(session,official,'What discrepancies does it have?',
                'context-chat-key-0002',conversation_id)
            assert second and plan['tool']=='get_fdr_details'
            await service.execute(session,second.id)
            await session.commit()
            await session.refresh(second)
            assert second.status=='succeeded'
            assert second.steps[0]['result']['answer_source']=='llm-grounded'
            turns=list((await session.scalars(select(CommandExecution).where(
                CommandExecution.user_id==official.id,
                CommandExecution.conversation_id==conversation_id).order_by(CommandExecution.id))).all())
            assert len(turns)==2 and turns[0].interpreted_plan['mode']=='chat'
            third,task_plan=await service.interpret(session,official,
                'What is the status of that operation?','context-chat-key-0003',conversation_id)
            assert task_plan['tool']=='get_task_status'
            assert task_plan['args']['command_id']==second.id
            await service.execute(session,third.id);await session.commit();await session.refresh(third)
            assert third.status=='succeeded'
            other=User(email='other-context@example.test',full_name='Other',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(other);await session.flush()
            assert await service._conversation_context(session,other,conversation_id)==[]
        await engine.dispose()
    asyncio.run(run())


def test_conversational_greeting_with_low_intent_confidence_routes_to_chat_not_error(monkeypatch):
    import app.services.command_service as service
    import app.services.llm_service as llm_service

    async def low_confidence_parser(text,conversation=None,actor_role=None):
        assert text=='Hi'
        raise InvalidStateTransition('Could not identify a supported command.')

    async def real_chat_path(question,fallback,conversation=None):
        assert question=='Hi' and conversation==[]
        return 'Hello! What would you like help with?','llm-chat'

    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,
            connect_args={'check_same_thread':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(service,'_interpret_text',low_confidence_parser)
        monkeypatch.setattr(llm_service,'generate_command_chat_reply',real_chat_path)
        async with factory() as session:
            official=User(email='greeting-official@example.test',full_name='Official',password_hash='x',
                role=Role.AICTE_OFFICIAL.value,status='active',is_active=True)
            session.add(official);await session.flush()
            command,result=await service.interpret(session,official,'Hi','greeting-command-0001','greeting-conversation-1')
            assert command is None and result['mode']=='chat'
            assert result['reply']=='Hello! What would you like help with?'
            assert await session.scalar(select(CommandExecution.id).where(CommandExecution.conversation_id=='greeting-conversation-1'))
        await engine.dispose()
    asyncio.run(run())


def test_chat_reply_uses_configured_llm_without_structured_output(monkeypatch):
    from types import SimpleNamespace
    import app.services.llm_service as service

    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'content':'Hello! I can help with FDR questions.'}}]}

    class Client:
        def __init__(self,timeout): assert timeout==4
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,json,headers):
            assert url=='https://ollama.test/v1/chat/completions'
            assert json['model']=='gemma4:31b'
            assert headers['Authorization']=='Bearer test-key'
            assert 'response_format' not in json
            assert 'never infer case-specific facts' in json['messages'][0]['content']
            assert json['messages'][1:3]==[
                {'role':'user','content':'Earlier followup: FDR-42'},
                {'role':'assistant','content':'Previous assistant chat context.'},
            ]
            assert json['messages'][-1]=={'role':'user','content':'Hello'}
            return Response()

    monkeypatch.setattr(service,'get_settings',lambda:SimpleNamespace(
        command_llm_enabled=True,command_llm_api_url='https://ollama.test/v1/chat/completions',
        command_llm_api_key='test-key',command_llm_model='gemma4:31b',command_llm_timeout=4))
    monkeypatch.setattr(service.httpx,'AsyncClient',Client)
    reply,source=asyncio.run(service.generate_command_chat_reply('Hello','fallback',[
        {'role':'user','content':'Earlier followup: FDR-42'},
        {'role':'assistant','content':'Previous assistant chat context.'},
    ]))
    assert reply=='Hello! I can help with FDR questions.'
    assert source=='llm-chat'


def test_chat_reply_reports_provider_http_status_without_logging_credentials(monkeypatch, caplog):
    from types import SimpleNamespace
    import httpx
    import app.services.llm_service as service

    class Client:
        def __init__(self, timeout): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json, headers):
            request = httpx.Request('POST', url)
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError('Unauthorized', request=request, response=response)

    monkeypatch.setattr(service, 'get_settings', lambda: SimpleNamespace(
        command_llm_enabled=True, command_llm_api_url='https://ollama.test/v1/chat/completions',
        command_llm_api_key='test-key', command_llm_model='gemma4:31b', command_llm_timeout=4,
    ))
    monkeypatch.setattr(service.httpx, 'AsyncClient', Client)
    reply, source = asyncio.run(service.generate_command_chat_reply('Hello', 'fallback'))

    assert reply == 'fallback'
    assert source == 'deterministic-chat-fallback'
    assert 'HTTP 401 from ollama.test' in caplog.text
    assert 'test-key' not in caplog.text


def test_grounded_assistant_reply_uses_llm_but_falls_back_when_disabled(monkeypatch):
    from types import SimpleNamespace
    import app.services.llm_service as service

    monkeypatch.setattr(service, 'get_settings', lambda: SimpleNamespace(command_llm_enabled=False))
    result = asyncio.run(service.generate_grounded_reply('What next?', 'get_case_state', {}, 'Fallback answer'))
    assert result == 'Fallback answer'


def test_grounded_assistant_reply_uses_tool_result_with_configured_llm(monkeypatch):
    from types import SimpleNamespace
    import app.services.llm_service as service

    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices': [{'message': {'content': 'Your FDR is awaiting review. Please wait for the official decision.'}}]}

    class Client:
        def __init__(self, timeout): assert timeout == 4
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json, headers):
            assert url == 'http://ollama/v1/chat/completions'
            assert json['model'] == 'qwen2.5:3b'
            assert headers['Authorization'] == 'Bearer test-token'
            assert 'awaiting_official_decision' in json['messages'][1]['content']
            assert 'what should I do' in json['messages'][1]['content']
            return Response()

    monkeypatch.setattr(service, 'get_settings', lambda: SimpleNamespace(
        command_llm_enabled=True,
        command_llm_api_url='http://ollama/v1/chat/completions',
        command_llm_api_key='test-token',
        ollama_api_key='ocr-only-token',
        command_llm_model='qwen2.5:3b',
        command_llm_timeout=4,
    ))
    monkeypatch.setattr(service.httpx, 'AsyncClient', Client)
    result = asyncio.run(service.generate_grounded_reply(
        'what should I do', 'get_case_state', {'lifecycle_state': 'awaiting_official_decision'}, 'fallback'
    ))
    assert 'awaiting review' in result


def test_grounded_assistant_reply_falls_back_when_provider_is_unavailable(monkeypatch):
    from types import SimpleNamespace
    import httpx
    import app.services.llm_service as service

    class Client:
        def __init__(self, timeout): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise httpx.ConnectError('provider offline')

    monkeypatch.setattr(service, 'get_settings', lambda: SimpleNamespace(
        command_llm_enabled=True, command_llm_api_url='http://unavailable/v1/chat/completions',
        command_llm_api_key='', command_llm_model='model', command_llm_timeout=1,
    ))
    monkeypatch.setattr(service.httpx, 'AsyncClient', Client)
    result = asyncio.run(service.generate_grounded_reply(
        'What next?', 'get_case_state', {'lifecycle_state': 'submitted'}, 'Deterministic next-step guidance.'
    ))
    assert result == 'Deterministic next-step guidance.'
