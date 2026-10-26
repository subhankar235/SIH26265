import asyncio
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
from sqlalchemy.pool import StaticPool
import pytest
from app.core.database import Base
from app.core.enums import Role,ExecutionState,LifecycleState,AuthorizationState
from app.core.exceptions import InvalidStateTransition,NotFound
from app.models import FDR,Institution,User
from app.models.workflow import CommandExecution,OutboxEvent,WorkflowInstance
from app.services.command_service import interpret,confirm,_interpret_text


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
            session.add_all([institution_user,official]);await session.flush()
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
            command,plan=await interpret(session,official,'Pause FDR-1024','official-cmd-key-3')
            assert command.requires_confirmation and command.status=='planned'
            fdr.status='verified'
            with pytest.raises(InvalidStateTransition,match='PLAN_CHANGED'):
                await confirm(session,official,command.id,command.plan_hash)
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
