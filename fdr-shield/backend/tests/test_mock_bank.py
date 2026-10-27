from fastapi.testclient import TestClient
from mock_bank_api.main import app
from app.services.bank_verification_service import verify_with_bank
import asyncio
import app.services.bank_verification_service as bank_service

def test_demo_bank_verify_and_unknown_number():
    client=TestClient(app)
    ok=client.post('/sbi/v1/fdr/verify',json={'fdr_number':'SBI100001','holder_name':'ABC Institute'})
    assert ok.status_code==200 and ok.json()['found'] is True
    no=client.post('/pnb/v1/fdr/verify',json={'fdr_number':'PNB999999','holder_name':'Unknown'})
    assert no.status_code==200 and no.json()['found'] is False


def test_unsupported_bank_is_reported_as_unavailable_not_no_match():
    result=asyncio.run(verify_with_bank('ICICI Bank','FDIN3021456789','Customer'))
    assert result.found is False
    assert result.verification_status=='unsupported_bank'
    assert 'does not support ICICI Bank' in result.verification_message


def test_supported_bank_no_match_is_distinguished_from_unsupported(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'found':False}

    class Client:
        def __init__(self, timeout): assert timeout==5
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            assert url.endswith('/sbi/v1/fdr/verify')
            return Response()

    monkeypatch.setattr(bank_service.httpx,'AsyncClient',Client)
    result=asyncio.run(bank_service.verify_with_bank('SBI','SBI-123','Customer'))
    assert result.verification_status=='no_match'
    assert 'demo bank gateway' in result.verification_message
