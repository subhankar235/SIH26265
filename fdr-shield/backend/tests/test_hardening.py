import asyncio
from types import SimpleNamespace

import pytest

from app.core.deps import pagination, require_roles
from app.core.enums import AlertStage, TrustBadge
from app.schemas.verification import BankVerifyResponse, DiscrepancyOut
from app.services.notification_service import stage_for
from app.services.trust_score_service import compute_badge
from app.integrations import storage_client
from pathlib import Path


@pytest.mark.parametrize('role,allowed', [
    ('institution', False), ('aicte_official', True), ('admin', True),
])
def test_official_and_admin_role_guard(role, allowed):
    check = require_roles('aicte_official', 'admin')
    async def run():
        if allowed:
            assert (await check(user=SimpleNamespace(role=role))).role == role
        else:
            with pytest.raises(Exception): await check(user=SimpleNamespace(role=role))
    asyncio.run(run())


@pytest.mark.parametrize('days,expected', [
    (180, None), (91, None), (90, AlertStage.T_90), (61, AlertStage.T_90),
    (30, AlertStage.T_30), (1, AlertStage.T_30), (0, AlertStage.T_0), (-1, AlertStage.T_0),
])
def test_alert_stage_boundaries(days, expected):
    assert asyncio.run(stage_for(days)) == expected


@pytest.mark.parametrize('bank,discrepancies,expected', [
    (BankVerifyResponse(found=True, status='ACTIVE'), [], TrustBadge.BANK_VERIFIED),
    (BankVerifyResponse(found=False), [], TrustBadge.SELF_DECLARED),
    (BankVerifyResponse(found=True, status='CLOSED'), [], TrustBadge.SELF_DECLARED),
    (BankVerifyResponse(found=True, status='ACTIVE'), [DiscrepancyOut(field='amount', source='ocr', severity='high')], TrustBadge.MISMATCH),
    (BankVerifyResponse(found=False), [DiscrepancyOut(field='holder', source='ocr', severity='low')], TrustBadge.SELF_DECLARED),
])
def test_trust_badge_outcomes(bank, discrepancies, expected):
    assert asyncio.run(compute_badge(bank, discrepancies)) is expected


def test_all_null_ocr_without_bank_stays_yellow():
    assert asyncio.run(compute_badge(None, [])) is TrustBadge.SELF_DECLARED


@pytest.mark.parametrize('page,size,skip,limit', [
    (1, 20, 0, 20), (3, 10, 20, 10), (0, 0, 0, 1), (99, 1000, 9800, 100),
])
def test_pagination_is_bounded(page, size, skip, limit):
    result = pagination(page, size)
    assert (result.skip, result.limit) == (skip, limit)


def test_local_storage_roundtrip_and_five_minute_signed_url(tmp_path, monkeypatch):
    config = SimpleNamespace(storage_backend='local', storage_local_path=str(tmp_path), jwt_secret='test-secret',
                             s3_endpoint='', s3_access_key='', s3_secret_key='', s3_bucket='unused')
    monkeypatch.setattr(storage_client, 'get_settings', lambda: config)
    storage_client.ensure_bucket()
    storage_client.put('12/fdr_scan/receipt.png', b'PNG sample', 'image/png')
    url = storage_client.presign('12/fdr_scan/receipt.png', 300)
    token = url.rsplit('/', 1)[1]
    assert storage_client.read_local_token(token) == b'PNG sample'
    assert Path(tmp_path, '12', 'fdr_scan', 'receipt.png').exists()


def test_local_storage_rejects_tampered_signed_url(tmp_path, monkeypatch):
    config = SimpleNamespace(storage_backend='local', storage_local_path=str(tmp_path), jwt_secret='test-secret',
                             s3_endpoint='', s3_access_key='', s3_secret_key='', s3_bucket='unused')
    monkeypatch.setattr(storage_client, 'get_settings', lambda: config)
    with pytest.raises(ValueError): storage_client.read_local_token('invalid.token.signature')


def test_s3_presigned_url_uses_browser_reachable_endpoint(monkeypatch):
    config = SimpleNamespace(storage_backend='minio', s3_endpoint='http://minio:9000',
        s3_public_endpoint='http://localhost:9000', s3_access_key='access',
        s3_secret_key='secret', s3_region='us-east-1', s3_bucket='fdr-documents')
    endpoints = []

    class FakeS3:
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            assert operation == 'get_object'
            assert Params == {'Bucket': 'fdr-documents', 'Key': '1/fdr_scan/receipt.png'}
            assert ExpiresIn == 300
            return f'{endpoints[-1]}/fdr-documents/1/fdr_scan/receipt.png?signature=test'

    def fake_boto_client(service, **kwargs):
        assert service == 's3'
        endpoints.append(kwargs['endpoint_url'])
        return FakeS3()

    monkeypatch.setattr(storage_client, 'get_settings', lambda: config)
    monkeypatch.setattr(storage_client.boto3, 'client', fake_boto_client)
    url = storage_client.presign('1/fdr_scan/receipt.png')
    assert endpoints == ['http://localhost:9000']
    assert url.startswith('http://localhost:9000/')


def test_s3_client_uses_region_and_path_style_for_neon_storage(monkeypatch):
    config = SimpleNamespace(storage_backend='s3',
        s3_endpoint='https://branch.storage.aws.neon.tech', s3_public_endpoint='',
        s3_access_key='access', s3_secret_key='secret', s3_region='us-east-2',
        s3_bucket='fdr-documents')
    captured = {}

    def fake_boto_client(service, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(storage_client, 'get_settings', lambda: config)
    monkeypatch.setattr(storage_client.boto3, 'client', fake_boto_client)
    storage_client._client()

    assert captured['endpoint_url'] == config.s3_endpoint
    assert captured['region_name'] == 'us-east-2'
    assert captured['config'].s3['addressing_style'] == 'path'
    assert captured['aws_access_key_id'] == 'access'
    assert captured['aws_secret_access_key'] == 'secret'


def test_dashboard_redis_cache_uses_bounded_timeouts_and_closes_client(monkeypatch):
    import redis
    from app.services import dashboard_service

    seen = {}

    class FakeRedis:
        def get(self, key): return None
        def close(self): seen['closed'] = True

    def fake_from_url(cls, url, **kwargs):
        seen.update(kwargs)
        return FakeRedis()

    monkeypatch.setattr(redis.Redis, 'from_url', classmethod(fake_from_url))
    assert asyncio.run(dashboard_service._cache_get('dashboard:test')) is None
    assert seen['socket_connect_timeout'] <= 0.25
    assert seen['socket_timeout'] <= 0.25
    assert seen['retry_on_timeout'] is False
    assert seen['closed'] is True
