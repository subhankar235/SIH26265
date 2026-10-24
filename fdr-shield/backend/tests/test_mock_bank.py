from fastapi.testclient import TestClient
from mock_bank_api.main import app

def test_demo_bank_verify_and_unknown_number():
    client=TestClient(app)
    ok=client.post('/sbi/v1/fdr/verify',json={'fdr_number':'SBI100001','holder_name':'ABC Institute'})
    assert ok.status_code==200 and ok.json()['found'] is True
    no=client.post('/pnb/v1/fdr/verify',json={'fdr_number':'PNB999999','holder_name':'Unknown'})
    assert no.status_code==200 and no.json()['found'] is False
