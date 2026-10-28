from fastapi.testclient import TestClient
from mock_bank_api.main import app
from app.services.bank_verification_service import verify_with_bank
from app.services.bank_names import bank_code_for_name
import asyncio
import app.services.bank_verification_service as bank_service
import pytest

def test_demo_bank_verify_and_unknown_number():
    client=TestClient(app)
    ok=client.post('/sbi/v1/fdr/verify',json={'fdr_number':'SBI100001','holder_name':'ABC Institute'})
    assert ok.status_code==200 and ok.json()['found'] is True
    no=client.post('/pnb/v1/fdr/verify',json={'fdr_number':'PNB999999','holder_name':'Unknown'})
    assert no.status_code==200 and no.json()['found'] is False


def test_hdfc_and_icici_sample_scans_have_matching_demo_records():
    client=TestClient(app)
    hdfc=client.post('/hdfc/v1/fdr/verify',json={
        'fdr_number':'HDFCFD2406147890','holder_name':'MR. SUBHANKAR NATH / MRS. RITU NATH'})
    assert hdfc.status_code==200
    assert hdfc.json()=={'found':True,'status':'ACTIVE','amount':500000,
        'maturity_date':'2027-06-14','holder_name':'MR. SUBHANKAR NATH / MRS. RITU NATH',
        'lien_in_favor_of':'AICTE'}
    icici=client.post('/icici/v1/fdr/verify',json={
        'fdr_number':'ICIFD2404056789','holder_name':'MR. ARJUN VERMA / MRS. POOJA VERMA'})
    assert icici.status_code==200
    assert icici.json()=={'found':True,'status':'ACTIVE','amount':300000,
        'maturity_date':'2026-04-05','holder_name':'MR. ARJUN VERMA / MRS. POOJA VERMA',
        'lien_in_favor_of':'AICTE'}
    assert 'icici' in client.get('/banks').json()


def test_sbi_full_bank_name_and_sample_record_are_supported():
    client=TestClient(app)
    response=client.post('/sbi/v1/fdr/verify',json={
        'fdr_number':'SBIFD20240123456',
        'holder_name':'MR. VIKRAM KUMAR SINGH / MRS. ANJALI SINGH'})
    assert response.status_code==200 and response.json()['found'] is True
    assert bank_code_for_name('State Bank of India')=='sbi'
    assert bank_code_for_name('HDFC Bank Limited')=='hdfc'
    assert bank_code_for_name('ICICI Bank')=='icici'
    assert bank_code_for_name('Unknown Bank') is None


@pytest.mark.parametrize(('name','code'),[
    ('SBI','sbi'),('State Bank of India','sbi'),('The State Bank of India (SBI)','sbi'),
    ('PNB','pnb'),('Punjab National Bank Ltd.','pnb'),
    ('HDFC Bank Limited','hdfc'),('HDFC Bank Ltd.','hdfc'),
    ('ICICI Bank Limited','icici'),('ICICI Bank Ltd.','icici'),
])
def test_bank_name_variants_map_to_supported_mock_adapters(name,code):
    assert bank_code_for_name(name)==code


def test_icici_demo_record_is_supported_by_verification_service(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'found':True,'status':'ACTIVE','amount':300000,
            'maturity_date':'2026-04-05','holder_name':'MR. ARJUN VERMA / MRS. POOJA VERMA'}

    class Client:
        def __init__(self, timeout): assert timeout==5
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            assert url.endswith('/icici/v1/fdr/verify')
            assert json['fdr_number']=='ICIFD2404056789'
            return Response()

    monkeypatch.setattr(bank_service.httpx,'AsyncClient',Client)
    result=asyncio.run(verify_with_bank('ICICI Bank','ICIFD2404056789','MR. ARJUN VERMA / MRS. POOJA VERMA'))
    assert result.found is True
    assert result.verification_status=='matched'


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
