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
    ('institution', False), ('scrutiny_officer', False), ('bureau_chief', True), ('admin', True),
])
def test_chief_only_role_guard(role, allowed):
    check = require_roles('bureau_chief', 'admin')
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
