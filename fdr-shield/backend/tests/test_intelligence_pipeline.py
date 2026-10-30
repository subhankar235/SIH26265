import pytest
import json
import hashlib
import httpx


def test_assessment_output_rejects_bad_schema_and_invalid_evidence():
    from app.services.intelligence_service import validate_assessment

    evidence = [{'field': 'amount', 'severity': 'high'}]
    with pytest.raises(ValueError):
        validate_assessment({'assessment': 'approved', 'summary': 'verified', 'evidence_indices': []}, evidence)
    with pytest.raises(ValueError):
        validate_assessment({'assessment': 'additional_review', 'summary': 'Review',
                             'evidence_indices': [4]}, evidence)
    result = validate_assessment({'assessment': 'additional_review', 'summary': 'Invented claim',
                                  'evidence_indices': [0]}, evidence)
    assert result['summary'] == 'Additional review is suggested; verify the cited records.'


def test_synthetic_dataset_trains_real_candidate_but_never_promotes(tmp_path):
    pytest.importorskip('sklearn')
    from app.services.intelligence_training import (
        generate_synthetic_rows, promote_artifact, train_and_evaluate,
    )

    result = train_and_evaluate(generate_synthetic_rows(400, seed=5), output_dir=tmp_path, random_seed=9)
    assert result['origin'] == 'synthetic'
    assert result['metrics']['test_rows'] == 100
    assert result['deployment_status'] == 'candidate'
    assert result['promotion_eligible'] is False
    with pytest.raises(ValueError, match='real-data'):
        promote_artifact(result['artifact_dir'], tmp_path / 'active')


def test_training_rejects_missing_class_balance_and_mixed_provenance():
    from app.services.intelligence_training import generate_synthetic_rows, train_and_evaluate

    rows = generate_synthetic_rows(100, seed=3)
    rows[0]['origin'] = 'real'
    with pytest.raises(ValueError, match='consistent'):
        train_and_evaluate(rows)


def test_intelligence_configuration_is_separate_from_command_and_ocr():
    from app.core.intelligence_config import IntelligenceSettings

    settings = IntelligenceSettings(_env_file=None, enabled=True,
        fallback_enabled=True, fallback_base_url='http://ollama:11434', fallback_model='local-model')
    assert settings.enabled is True
    assert settings.fallback_model == 'local-model'
    assert not hasattr(settings, 'command_llm_api_key')
    assert not hasattr(settings, 'ollama_api_key')


def test_primary_artifact_sync_validates_and_caches_the_promoted_storage_version(monkeypatch, tmp_path):
    from app.core.intelligence_config import IntelligenceSettings
    from app.integrations import storage_client
    from app.services.intelligence_service import _sync_active_artifact

    artifact = b'unit-test-artifact-bytes'
    version = 'review-priority-test-version'
    metadata = {'artifact_version': version, 'origin': 'real', 'deployment_status': 'approved',
                'artifact_sha256': hashlib.sha256(artifact).hexdigest()}
    objects = {
        'private/active.json': json.dumps({'artifact_version': version,
            'artifact_storage_key': 'private/model.joblib', 'metadata_storage_key': 'private/model.json',
            'deployment_status': 'approved'}).encode(),
        'private/model.joblib': artifact,
        'private/model.json': json.dumps(metadata).encode(),
    }
    monkeypatch.setattr(storage_client, 'get', lambda key: objects[key])
    settings = IntelligenceSettings(_env_file=None, artifact_storage_prefix='private',
                                    primary_artifact_path=str(tmp_path / 'active'))
    _sync_active_artifact(settings)
    assert (tmp_path / 'active' / 'review-priority.joblib').read_bytes() == artifact
    cached = json.loads((tmp_path / 'active' / 'metadata.json').read_text(encoding='utf-8'))
    assert cached['artifact_version'] == version


@pytest.mark.asyncio
async def test_intelligence_disabled_returns_explicit_unavailable(monkeypatch):
    from app.core.intelligence_config import IntelligenceSettings, get_intelligence_settings
    from app.services.intelligence_service import assess_fdr

    monkeypatch.setattr('app.services.intelligence_service.get_intelligence_settings',
        lambda: IntelligenceSettings(_env_file=None, enabled=False))
    result = await assess_fdr({'evidence': []})
    assert result['assessment'] == 'unavailable'
    assert result['provider'] == 'none'


@pytest.mark.asyncio
async def test_primary_failure_uses_validated_fallback(monkeypatch):
    from app.core.intelligence_config import IntelligenceSettings
    from app.services import intelligence_service

    monkeypatch.setattr(intelligence_service, 'get_intelligence_settings', lambda: IntelligenceSettings(
        _env_file=None, enabled=True, fallback_enabled=True,
        fallback_base_url='http://ollama:11434', fallback_model='review-model'))
    monkeypatch.setattr(intelligence_service, '_primary_assessment',
                        lambda _: (_ for _ in ()).throw(RuntimeError('artifact unavailable')))

    async def fallback(features, reason):
        assert reason == 'RuntimeError'
        return {'assessment': 'additional_review',
                'summary': 'Additional review is suggested; verify the cited records.',
                'evidence_indices': [0], 'provider': 'fallback'}

    monkeypatch.setattr(intelligence_service, '_fallback_assessment', fallback)
    result = await intelligence_service.assess_fdr({'evidence': [{'field': 'amount', 'severity': 'high'}]})
    assert result['provider'] == 'fallback'
    assert result['assessment'] == 'additional_review'


@pytest.mark.asyncio
async def test_valid_primary_assessment_does_not_call_fallback(monkeypatch):
    from app.core.intelligence_config import IntelligenceSettings
    from app.services import intelligence_service

    monkeypatch.setattr(intelligence_service, 'get_intelligence_settings', lambda: IntelligenceSettings(
        _env_file=None, enabled=True, fallback_enabled=True,
        fallback_base_url='http://ollama:11434', fallback_model='review-model'))
    monkeypatch.setattr(intelligence_service, '_primary_assessment', lambda _: {
        'assessment': 'additional_review', 'summary': 'ignored', 'evidence_indices': [0],
        'model_version': 'private-version'})

    async def fallback(*_):
        raise AssertionError('fallback must not run after a valid primary result')

    monkeypatch.setattr(intelligence_service, '_fallback_assessment', fallback)
    result = await intelligence_service.assess_fdr({'evidence': [{'field': 'amount', 'severity': 'high'}],
        'discrepancy_count': 1, 'high_discrepancy_count': 1, 'missing_fields': 0})
    assert result['provider'] == 'primary'
    assert result['model_version'] == 'private-version'
    assert result['summary'] == 'Additional review is suggested; verify the cited records.'


@pytest.mark.asyncio
async def test_both_provider_failures_return_manual_review_status(monkeypatch):
    from app.core.intelligence_config import IntelligenceSettings
    from app.services import intelligence_service

    monkeypatch.setattr(intelligence_service, 'get_intelligence_settings', lambda: IntelligenceSettings(
        _env_file=None, enabled=True, fallback_enabled=True,
        fallback_base_url='http://ollama:11434', fallback_model='review-model',
        fallback_timeout_seconds=.1, total_timeout_seconds=1))
    monkeypatch.setattr(intelligence_service, '_primary_assessment',
                        lambda _: (_ for _ in ()).throw(RuntimeError('artifact unavailable')))

    async def fallback(*_):
        raise TimeoutError('provider unavailable')

    monkeypatch.setattr(intelligence_service, '_fallback_assessment', fallback)
    result = await intelligence_service.assess_fdr({'evidence': []})
    assert result['assessment'] == 'unavailable'
    assert result['provider'] == 'none'


@pytest.mark.asyncio
async def test_ollama_compatible_fallback_uses_backend_secret_and_discards_generated_claims(monkeypatch):
    from app.core.intelligence_config import IntelligenceSettings
    from app.services import intelligence_service

    settings = IntelligenceSettings(_env_file=None, enabled=True, fallback_enabled=True,
        fallback_base_url='http://ollama.test:11434', fallback_model='fdr-review',
        fallback_api_key='server-only-test-secret')
    monkeypatch.setattr(intelligence_service, 'get_intelligence_settings', lambda: settings)
    observed = {}

    def handler(request):
        observed['authorization'] = request.headers.get('Authorization')
        observed['url'] = str(request.url)
        body = json.loads(request.content)
        observed['message'] = json.loads(body['messages'][0]['content'])
        output = {'assessment': 'additional_review', 'summary': 'This is definitely fraud.',
                  'evidence_indices': [0]}
        return httpx.Response(200, json={'message': {'content': json.dumps(output)}})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(intelligence_service.httpx, 'AsyncClient',
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    features = {'amount': 1000.0, 'tenure_days': 365, 'missing_fields': 0,
        'discrepancy_count': 1, 'high_discrepancy_count': 1,
        'evidence': [{'field': 'amount', 'severity': 'high'}]}
    result = await intelligence_service._fallback_assessment(features, 'artifact unavailable')
    assert observed['authorization'] == 'Bearer server-only-test-secret'
    assert observed['url'] == 'http://ollama.test:11434/api/chat'
    assert 'secret' not in json.dumps(observed['message'])
    assert result['assessment'] == 'additional_review'
    assert 'fraud' not in result['summary'].lower()


@pytest.mark.asyncio
async def test_ollama_fallback_rejects_unsupported_output(monkeypatch):
    from app.core.intelligence_config import IntelligenceSettings
    from app.services import intelligence_service

    monkeypatch.setattr(intelligence_service, 'get_intelligence_settings', lambda: IntelligenceSettings(
        _env_file=None, fallback_enabled=True, fallback_base_url='http://ollama.test', fallback_model='review'))
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200,
        json={'message': {'content': '{"assessment":"approved","summary":"ok","evidence_indices":[]}'}}))
    monkeypatch.setattr(intelligence_service.httpx, 'AsyncClient',
        lambda **kwargs: original_client(transport=transport, **kwargs))
    with pytest.raises(ValueError, match='category is unsupported'):
        await intelligence_service._fallback_assessment({'evidence': []}, 'primary invalid')


@pytest.mark.asyncio
async def test_ollama_timeout_retries_are_bounded_and_end_in_manual_review(monkeypatch):
    from app.core.intelligence_config import IntelligenceSettings
    from app.services import intelligence_service

    monkeypatch.setattr(intelligence_service, 'get_intelligence_settings', lambda: IntelligenceSettings(
        _env_file=None, enabled=True, fallback_enabled=True, fallback_base_url='http://ollama.test',
        fallback_model='review', fallback_timeout_seconds=.1, total_timeout_seconds=1,
        fallback_max_retries=1))
    monkeypatch.setattr(intelligence_service, '_primary_assessment',
        lambda _: (_ for _ in ()).throw(RuntimeError('no primary artifact')))
    attempts = {'count': 0}

    def handler(request):
        attempts['count'] += 1
        raise httpx.ReadTimeout('provider timed out')

    original_client = httpx.AsyncClient
    monkeypatch.setattr(intelligence_service.httpx, 'AsyncClient',
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    result = await intelligence_service.assess_fdr({'evidence': []})
    assert attempts['count'] == 2
    assert result['assessment'] == 'unavailable'
    assert result['provider'] == 'none'
