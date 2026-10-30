"""Internal, advisory FDR triage with a validated provider fallback.

Deterministic verification remains authoritative. This service only produces a
review-priority note and returns unavailable when no safe provider can do so.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.intelligence_config import get_intelligence_settings

logger = logging.getLogger(__name__)
_PRIMARY_INFERENCE_SLOTS = threading.BoundedSemaphore(2)
_FALLBACK_INFERENCE_SLOTS = threading.BoundedSemaphore(4)
_ARTIFACT_SYNC_LOCK = threading.Lock()
FEATURES = ('amount', 'tenure_days', 'missing_fields', 'discrepancy_count', 'high_discrepancy_count')
LABELS = {'routine', 'additional_review'}


def build_features(*, amount: Any, issue_date: Any, maturity_date: Any,
                   declared: dict, extracted: dict, discrepancies: list[dict]) -> dict:
    try:
        amount_value = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount_value = None
    tenure = None
    if issue_date and maturity_date:
        try:
            tenure = (maturity_date - issue_date).days
        except (TypeError, AttributeError):
            tenure = None
    missing = sum(extracted.get(key) in (None, '') for key in
                  ('fdr_number', 'bank_name', 'amount', 'issue_date', 'maturity_date'))
    return {
        'amount': amount_value,
        'tenure_days': tenure,
        'missing_fields': int(missing),
        'discrepancy_count': len(discrepancies),
        'high_discrepancy_count': sum(1 for item in discrepancies if item.get('severity') == 'high'),
        'evidence': [{'field': str(d.get('field', ''))[:80],
                      'severity': str(d.get('severity', ''))[:20]} for d in discrepancies[:50]],
    }


def validate_assessment(value: object, evidence: list[dict], features: dict | None = None) -> dict:
    if not isinstance(value, dict) or set(value) != {'assessment', 'summary', 'evidence_indices'}:
        raise ValueError('Assessment output has an invalid schema')
    if value['assessment'] not in LABELS | {'insufficient_evidence'}:
        raise ValueError('Assessment category is unsupported')
    summary = value['summary']
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise ValueError('Assessment summary is invalid')
    indices = value['evidence_indices']
    if not isinstance(indices, list) or len(indices) > 20:
        raise ValueError('Evidence references are invalid')
    if any(isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(evidence)
           for index in indices):
        raise ValueError('Assessment references unavailable evidence')
    if value['assessment'] == 'insufficient_evidence' and indices:
        raise ValueError('Insufficient-evidence result cannot claim supporting evidence')
    if value['assessment'] == 'additional_review' and not indices:
        raise ValueError('Additional review requires at least one cited evidence item')
    if features and value['assessment'] == 'routine' and (
            features.get('high_discrepancy_count', 0) > 0
            or features.get('discrepancy_count', 0) > 2
            or features.get('missing_fields', 0) >= 3):
        raise ValueError('Routine assessment conflicts with recorded discrepancy evidence')
    # Do not expose free-form generated claims. The persisted explanation is
    # deterministic and only describes the allowed advisory category.
    messages = {
        'routine': 'No additional review priority was identified by this advisory assessment.',
        'additional_review': 'Additional review is suggested; verify the cited records.',
        'insufficient_evidence': 'Available evidence is insufficient for an advisory assessment.',
    }
    return {'assessment': value['assessment'], 'summary': messages[value['assessment']],
            'evidence_indices': indices}


def _load_and_assess_primary(features: dict) -> dict:
    settings = get_intelligence_settings()
    _sync_active_artifact(settings)
    active = Path(settings.primary_artifact_path)
    artifact = active / 'review-priority.joblib'
    metadata = active / 'metadata.json'
    if not artifact.is_file() or not metadata.is_file():
        raise RuntimeError('approved primary artifact is unavailable')
    import joblib
    details = json.loads(metadata.read_text(encoding='utf-8'))
    if details.get('deployment_status') != 'approved' or details.get('origin') != 'real':
        raise RuntimeError('primary artifact is not approved for operational use')
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if details.get('artifact_sha256') != artifact_hash:
        raise RuntimeError('primary artifact checksum validation failed')
    model = joblib.load(artifact)
    vector = [[features.get(name) for name in FEATURES]]
    prediction = str(model.predict(vector)[0])
    if prediction not in LABELS:
        raise ValueError('primary artifact returned an unsupported category')
    return {'assessment': prediction, 'summary': 'Case priority estimated from the approved review model.',
            'evidence_indices': list(range(min(len(features.get('evidence', [])), 20))),
            'provider': 'primary', 'model_version': details.get('artifact_version')}


def _sync_active_artifact(settings) -> None:
    """Fetch the promoted artifact pointer from private shared object storage."""
    with _ARTIFACT_SYNC_LOCK:
        _sync_active_artifact_locked(settings)


def _sync_active_artifact_locked(settings) -> None:
    from app.integrations import storage_client

    prefix = settings.artifact_storage_prefix.strip('/')
    manifest = json.loads(storage_client.get(f'{prefix}/active.json'))
    if manifest.get('deployment_status') != 'approved':
        raise RuntimeError('No approved primary artifact is active')
    artifact_key, metadata_key = manifest.get('artifact_storage_key'), manifest.get('metadata_storage_key')
    if not isinstance(artifact_key, str) or not isinstance(metadata_key, str):
        raise RuntimeError('Active artifact manifest is incomplete')
    active = Path(settings.primary_artifact_path)
    artifact_path, metadata_path = active / 'review-priority.joblib', active / 'metadata.json'
    try:
        cached = json.loads(metadata_path.read_text(encoding='utf-8'))
        if cached.get('artifact_version') == manifest.get('artifact_version'):
            digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if digest == cached.get('artifact_sha256') and cached.get('deployment_status') == 'approved':
                return
    except (OSError, ValueError, TypeError):
        pass
    artifact = storage_client.get(artifact_key)
    metadata_bytes = storage_client.get(metadata_key)
    details = json.loads(metadata_bytes)
    if (details.get('deployment_status') != 'approved' or details.get('origin') != 'real'
            or details.get('artifact_version') != manifest.get('artifact_version')
            or hashlib.sha256(artifact).hexdigest() != details.get('artifact_sha256')):
        raise RuntimeError('Promoted artifact failed provenance or checksum validation')
    active.mkdir(parents=True, exist_ok=True)
    artifact_tmp, metadata_tmp = active / '.review-priority.joblib.tmp', active / '.metadata.json.tmp'
    artifact_tmp.write_bytes(artifact)
    metadata_tmp.write_bytes(metadata_bytes)
    artifact_tmp.replace(artifact_path)
    metadata_tmp.replace(metadata_path)


def _primary_assessment(features: dict) -> dict:
    if not _PRIMARY_INFERENCE_SLOTS.acquire(blocking=False):
        raise RuntimeError('primary inference capacity is currently full')
    try:
        return _load_and_assess_primary(features)
    finally:
        _PRIMARY_INFERENCE_SLOTS.release()


async def _fallback_assessment(features: dict, reason: str) -> dict:
    settings = get_intelligence_settings()
    if not settings.fallback_enabled:
        raise RuntimeError('fallback provider is disabled')
    evidence = features.get('evidence', [])
    prompt = {
        'task': 'Provide a non-authoritative FDR case review-priority assessment from supplied evidence only.',
        'allowed_assessment': ['routine', 'additional_review', 'insufficient_evidence'],
        'rules': [
            'Do not claim fraud, authenticity, bank verification, approval, or rejection.',
            'Do not invent facts or evidence. Cite only zero-based evidence_indices supplied.',
            'Use insufficient_evidence when supplied evidence does not support a priority assessment.',
            'Return one JSON object with exactly assessment, summary, evidence_indices.',
        ],
        'primary_failure': reason[:120], 'features': {key: features.get(key) for key in FEATURES},
        'evidence': evidence,
    }
    headers = {'Authorization': f'Bearer {settings.fallback_api_key}'} if settings.fallback_api_key else {}
    body = {'model': settings.fallback_model, 'stream': False, 'format': 'json',
            'options': {'temperature': 0}, 'messages': [{'role': 'user', 'content': json.dumps(prompt)}]}
    if not _FALLBACK_INFERENCE_SLOTS.acquire(blocking=False):
        raise RuntimeError('secondary assessment capacity is currently full')
    try:
        async with httpx.AsyncClient(timeout=settings.fallback_timeout_seconds) as client:
            response = await client.post(f'{settings.fallback_base_url.rstrip("/")}/api/chat',
                                         json=body, headers=headers)
            response.raise_for_status()
        content = response.json().get('message', {}).get('content', '')
        result = validate_assessment(json.loads(content), evidence, features)
        return {**result, 'provider': 'fallback'}
    finally:
        _FALLBACK_INFERENCE_SLOTS.release()


async def assess_fdr(features: dict) -> dict:
    """Try approved primary inference, then a bounded validated secondary provider."""
    settings = get_intelligence_settings()
    if not settings.enabled:
        return {'assessment': 'unavailable', 'summary': 'Standard scrutiny applies.',
                'evidence_indices': [], 'provider': 'none'}
    evidence = features.get('evidence', [])
    deadline = time.monotonic() + settings.total_timeout_seconds
    try:
        primary_budget = min(settings.inference_timeout_seconds, deadline - time.monotonic())
        if primary_budget <= 0:
            raise asyncio.TimeoutError()
        primary = await asyncio.wait_for(asyncio.to_thread(_primary_assessment, features),
                                         timeout=primary_budget)
        return {**validate_assessment({key: primary[key] for key in
                ('assessment', 'summary', 'evidence_indices')}, evidence, features),
                'provider': 'primary', 'model_version': primary.get('model_version')}
    except Exception as exc:
        primary_reason = type(exc).__name__
        logger.info('Internal primary assessment unavailable; applying configured fallback',
                    extra={'failure_class': primary_reason})
    last_error = None
    for attempt in range(settings.fallback_max_retries + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            return await asyncio.wait_for(_fallback_assessment(features, primary_reason),
                timeout=min(settings.fallback_timeout_seconds, remaining))
        except Exception as exc:
            last_error = exc
            if attempt < settings.fallback_max_retries:
                await asyncio.sleep(min(.1 * (attempt + 1), max(0, deadline - time.monotonic())))
    if last_error:
        logger.warning('Internal assessment unavailable; manual review remains required',
                       extra={'failure_class': type(last_error).__name__})
    return {'assessment': 'unavailable', 'summary': 'Automated review note unavailable; continue standard scrutiny.',
            'evidence_indices': [], 'provider': 'none'}
