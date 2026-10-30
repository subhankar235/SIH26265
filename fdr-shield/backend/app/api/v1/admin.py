"""Admin-only account management and registration approvals."""
<<<<<<< HEAD
import csv
import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Header, UploadFile, File, Form
=======
from fastapi import APIRouter, Body, Depends, HTTPException, Header
>>>>>>> a27ee110f6ba3d79cb2eb0cff239996b7f97ea26
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import Pagination, get_current_user, pagination, require_roles
from app.core.enums import Role
from app.core.exceptions import InvalidStateTransition
from app.models.user import User
from app.models.notification import Notification
from app.models.workflow import NotificationDeliveryAttempt, OutboxEvent
from app.schemas.auth import AdminUserCreate, AdminUserOut, AdminUserUpdate, RegistrationDecision, RegistrationDecisionRequest
from app.services import user_admin_service
<<<<<<< HEAD
from app.models.ml import MLModelVersion, MLTrainingJob
from app.models.workflow import WorkflowNodeExecution
from app.services.audit_service import record

router = APIRouter()
ADMIN = require_roles(Role.ADMIN)
logger = logging.getLogger(__name__)


@router.post('/intelligence/datasets/validate')
async def validate_intelligence_dataset(file: UploadFile = File(...),
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.core.intelligence_config import get_intelligence_settings
    from app.services.intelligence_training import read_training_csv, validate_training_rows
    payload = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Dataset file exceeds the 20 MiB upload limit.')
    root = Path(get_intelligence_settings().artifact_path).resolve()
    incoming = root / 'incoming'
    incoming.mkdir(parents=True, exist_ok=True)
    temporary = incoming / f'validate-{uuid.uuid4().hex}.csv'
    try:
        temporary.write_bytes(payload)
        rows = read_training_csv(temporary)
        report = validate_training_rows(rows)
        return {'valid': True, 'rows': len(rows), 'origin': report['origin'],
            'class_counts': report['class_counts'], 'dataset_sha256': report['dataset_sha256'],
            'feature_names': ['amount', 'tenure_days', 'missing_fields', 'discrepancy_count',
                              'high_discrepancy_count'],
            'promotion_eligible': False}
    except (ValueError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)


@router.post('/intelligence/training-jobs', status_code=202)
async def start_intelligence_training(file: UploadFile = File(...),
        dataset_reference: str = Form(''), random_seed: int = Form(20261030),
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.core.intelligence_config import get_intelligence_settings
    from app.services.intelligence_training import read_training_csv, validate_training_rows
    from app.workers.tasks_ml import train_review_priority_task
    payload = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Dataset file exceeds the 20 MiB upload limit.')
    root = Path(get_intelligence_settings().artifact_path).resolve()
    incoming = root / 'incoming'
    incoming.mkdir(parents=True, exist_ok=True)
    dataset = incoming / f'{uuid.uuid4().hex}.csv'
    try:
        dataset.write_bytes(payload)
        report = validate_training_rows(read_training_csv(dataset))
        if report['origin'] == 'real' and not dataset_reference.strip():
            raise ValueError('Real-data training requires an auditable dataset reference.')
        job = MLTrainingJob(status='QUEUED', origin=report['origin'],
            dataset_reference=dataset_reference.strip()[:255] or None,
            dataset_sha256=report['dataset_sha256'], row_count=sum(report['class_counts'].values()),
            class_counts=report['class_counts'], requested_by=actor.id)
        session.add(job)
        await session.flush()
        job_dataset = incoming / f'{job.id}-{uuid.uuid4().hex}.csv'
        dataset.replace(job_dataset)
        dataset = job_dataset
        await record(session, actor.id, 'ml_training_job', job.id, 'TRAINING_QUEUED', '',
            {'status': [None, 'QUEUED'], 'dataset_sha256': [None, report['dataset_sha256']],
             'origin': [None, report['origin']]})
        await session.commit()
        try:
            task = train_review_priority_task.delay(str(dataset), dataset_reference.strip(), random_seed,
                                                    actor.id, job.id)
            job.celery_task_id = task.id
            await session.commit()
        except Exception as exc:
            job = await session.get(MLTrainingJob, job.id)
            if job:
                job.status = 'FAILED'
                job.error_summary = f'Training queue unavailable: {type(exc).__name__}'
                await record(session, actor.id, 'ml_training_job', job.id, 'TRAINING_QUEUE_FAILED', '',
                    {'status': ['QUEUED', 'FAILED'], 'error_class': [None, type(exc).__name__]})
                await session.commit()
            dataset.unlink(missing_ok=True)
            raise HTTPException(503, 'Training worker is currently unavailable.') from exc
        return {'job_id': job.id, 'status': job.status, 'rows': job.row_count,
            'origin': job.origin}
    except (ValueError, csv.Error) as exc:
        dataset.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        dataset.unlink(missing_ok=True)
        raise


@router.get('/intelligence/training-jobs/{job_id}')
async def intelligence_training_job(job_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    job = await session.get(MLTrainingJob, job_id)
    if not job:
        raise HTTPException(404, 'Training job not found.')
    return {'job_id': job.id, 'status': job.status, 'origin': job.origin,
        'rows': job.row_count, 'dataset_sha256': job.dataset_sha256,
        'class_counts': job.class_counts, 'metrics': job.evaluation_metrics,
        'artifact_version': job.artifact_version, 'error': job.error_summary,
        'created_at': job.created_at.isoformat(), 'updated_at': job.updated_at.isoformat()}


@router.get('/intelligence/training-jobs')
async def list_intelligence_training_jobs(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    rows = list((await session.scalars(select(MLTrainingJob).order_by(
        MLTrainingJob.created_at.desc()).limit(100))).all())
    return [{'job_id': job.id, 'status': job.status, 'origin': job.origin, 'rows': job.row_count,
        'dataset_sha256': job.dataset_sha256, 'class_counts': job.class_counts,
        'metrics': job.evaluation_metrics, 'artifact_version': job.artifact_version,
        'error': job.error_summary, 'created_at': job.created_at.isoformat(),
        'updated_at': job.updated_at.isoformat()} for job in rows]


@router.get('/intelligence/artifacts')
async def intelligence_artifacts(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    rows = list((await session.scalars(select(MLModelVersion).where(
        MLModelVersion.use_case == 'review_priority').order_by(MLModelVersion.created_at.desc()).limit(100))).all())
    jobs = list((await session.scalars(select(MLTrainingJob).where(
        MLTrainingJob.artifact_version.is_not(None)).order_by(MLTrainingJob.created_at.desc()).limit(100))).all())
    job_by_version = {job.artifact_version: job for job in jobs}
    output = []
    for row in rows:
        metrics = row.evaluation_metrics or {}
        promotion_eligible = (not row.is_synthetic and metrics.get('precision_additional_review', 0) >= .8
                              and metrics.get('recall_additional_review', 0) >= .8)
        output.append({'artifact_version': row.version, 'task': row.use_case,
            'origin': 'synthetic' if row.is_synthetic else 'real', 'dataset_rows': row.training_rows,
            'class_counts': (job_by_version.get(row.version).class_counts if row.version in job_by_version else {}),
            'evaluation_metrics': metrics, 'evaluation_passed': bool(promotion_eligible),
            'deployment_status': {'APPROVED_ACTIVE': 'approved', 'SUPERSEDED': 'superseded'}.get(row.status, 'candidate'),
            'promotion_eligible': bool(promotion_eligible),
            'rollback_reference': (row.library_versions or {}).get('rollback_reference'),
            'created_at': row.created_at.isoformat()})
    return output


@router.post('/intelligence/artifacts/{version}/promote')
async def promote_intelligence_artifact(version: str, body: dict = Body(...),
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    if body.get('confirmed') is not True:
        raise HTTPException(422, 'Explicit confirmation is required.')
    from app.core.intelligence_config import get_intelligence_settings
    from app.services.intelligence_training import promote_artifact
    from app.services.audit_service import record as write_audit
    root = Path(get_intelligence_settings().artifact_path).resolve()
    candidate = (root / version).resolve()
    if root not in candidate.parents or candidate.name != version:
        raise HTTPException(404, 'Artifact version not found.')
    row = await session.scalar(select(MLModelVersion).where(
        MLModelVersion.use_case == 'review_priority', MLModelVersion.version == version))
    if not row or row.status not in {'CANDIDATE', 'SUPERSEDED'}:
        raise HTTPException(409, 'Artifact has no promotable training registry record.')
    try:
        from app.core.intelligence_config import get_intelligence_settings
        from app.integrations import storage_client
        settings = get_intelligence_settings()
        if not (candidate / 'metadata.json').is_file() or not (candidate / 'review-priority.joblib').is_file():
            keys = row.library_versions or {}
            artifact_key, metadata_key = keys.get('artifact_storage_key'), keys.get('metadata_storage_key')
            if not artifact_key or not metadata_key:
                raise ValueError('Candidate artifact is missing from private artifact storage.')
            candidate.mkdir(parents=True, exist_ok=True)
            (candidate / 'review-priority.joblib').write_bytes(storage_client.get(artifact_key))
            (candidate / 'metadata.json').write_bytes(storage_client.get(metadata_key))
        status = promote_artifact(candidate, get_intelligence_settings().primary_artifact_path)
        promoted_metadata = json.loads((candidate / 'metadata.json').read_text(encoding='utf-8'))
        storage_client.put(promoted_metadata['metadata_storage_key'],
                           (candidate / 'metadata.json').read_bytes(), 'application/json')
        active_manifest_key = f"{settings.artifact_storage_prefix.strip('/')}/active.json"
        active_manifest = {'artifact_version': version,
            'artifact_storage_key': promoted_metadata['artifact_storage_key'],
            'metadata_storage_key': promoted_metadata['metadata_storage_key'],
            'deployment_status': 'approved'}
        storage_client.put(active_manifest_key, json.dumps(active_manifest).encode(), 'application/json')
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, 'Private artifact storage is unavailable; deployment could not be completed.') from exc
    previous_status = row.status
    active_rows = list((await session.scalars(select(MLModelVersion).where(
        MLModelVersion.use_case == 'review_priority', MLModelVersion.status == 'APPROVED_ACTIVE',
        MLModelVersion.id != row.id))).all())
    for previous in active_rows:
        previous.status = 'SUPERSEDED'
        await write_audit(session, actor.id, 'ml_model_version', previous.id, 'ARTIFACT_SUPERSEDED', '',
            {'status': ['APPROVED_ACTIVE', 'SUPERSEDED']})
    row.status = 'APPROVED_ACTIVE'
    row.library_versions = {**(row.library_versions or {}),
        'rollback_reference': promoted_metadata.get('rollback_reference')}
    await write_audit(session, actor.id, 'ml_model_version', row.id, 'ARTIFACT_PROMOTED', '',
                      {'status': [previous_status, 'APPROVED_ACTIVE'], 'version': [None, version]})
    return status


@router.get('/intelligence/health')
async def intelligence_health(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.core.intelligence_config import get_intelligence_settings
    settings = get_intelligence_settings()
    active = Path(settings.primary_artifact_path)
    artifact_ready = False
    artifact_version = None
    artifact_sync_status = 'not_checked'
    if settings.enabled:
        try:
            from app.services.intelligence_service import _sync_active_artifact
            await asyncio.to_thread(_sync_active_artifact, settings)
            artifact_sync_status = 'available'
        except Exception as exc:
            artifact_sync_status = 'unavailable'
            logger.warning('Internal artifact synchronization check failed',
                           extra={'failure_class': type(exc).__name__})
    metadata_path = active / 'metadata.json'
    try:
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        artifact_ready = (metadata.get('deployment_status') == 'approved' and metadata.get('origin') == 'real'
                          and (active / 'review-priority.joblib').is_file())
        artifact_version = metadata.get('artifact_version') if artifact_ready else None
    except (OSError, ValueError, TypeError):
        pass
    inference_status = 'not_available'
    if settings.enabled and artifact_ready:
        try:
            from app.services.intelligence_service import _primary_assessment
            probe = {'amount': 1000.0, 'tenure_days': 365, 'missing_fields': 0,
                     'discrepancy_count': 0, 'high_discrepancy_count': 0, 'evidence': []}
            await asyncio.wait_for(asyncio.to_thread(_primary_assessment, probe), timeout=5)
            inference_status = 'healthy'
        except Exception:
            inference_status = 'unavailable'
    latest = await session.scalar(select(WorkflowNodeExecution).where(
        WorkflowNodeExecution.node_key == 'validate_fields', WorkflowNodeExecution.status == 'succeeded')
        .order_by(WorkflowNodeExecution.id.desc()).limit(1))
    assessment = (latest.output_ref or {}).get('review_assessment') if latest else None
    return {'enabled': settings.enabled, 'primary_artifact_ready': artifact_ready,
        'artifact_sync_status': artifact_sync_status,
        'primary_inference_health': inference_status,
        'active_version': artifact_version,
        'fallback_configured': settings.fallback_enabled and bool(settings.fallback_base_url and settings.fallback_model),
        'fallback_health': 'checked on demand' if settings.fallback_enabled else 'disabled',
        'last_assessment_at': latest.finished_at.isoformat() if latest and latest.finished_at else None,
        'last_assessment_provider': (assessment or {}).get('provider'),
        'last_assessment_status': (assessment or {}).get('assessment')}


@router.get('/intelligence/capabilities')
async def intelligence_capabilities(actor=Depends(ADMIN)):
    """Business-facing availability only; never returns internal provider settings."""
    import importlib.util
    from app.core.config import get_settings
    ocr = get_settings().ocr_engine.strip().lower()
    if ocr == 'disabled':
        document_status = 'unavailable'
        document_message = 'Document fields can still be reviewed and entered manually.'
    elif ocr == 'ollama_vision':
        document_status = 'unknown' if get_settings().ollama_base_url and get_settings().ollama_model else 'unavailable'
        document_message = ('Availability is confirmed while processing a submitted document.'
                            if document_status == 'unknown' else 'Document analysis is not fully configured.')
    elif ocr == 'easyocr':
        document_status = 'available' if importlib.util.find_spec('easyocr') else 'unavailable'
        document_message = 'Supported document fields can be extracted.' if document_status == 'available' else 'The configured document engine dependency is unavailable.'
    elif ocr == 'tesseract':
        document_status = 'available' if importlib.util.find_spec('pytesseract') else 'unavailable'
        document_message = 'Supported document fields can be extracted.' if document_status == 'available' else 'The configured document engine dependency is unavailable.'
    else:
        document_status = 'unavailable'
        document_message = 'Document analysis is not currently available.'
    return {'capabilities': [
        {'id': 'document_analysis', 'status': document_status, 'message': document_message},
        {'id': 'discrepancy_detection', 'status': 'available',
         'message': 'Declared, extracted, and available verification values are compared by existing validation rules.'},
        ({'id': 'anomaly_detection', 'status': 'available',
          'message': 'Advisory anomaly scoring is active over structured FDR features (amount, tenure, bank, declaration gaps). Findings suggest review only; they never auto-reject a case.'}
         if get_settings().ml_anomaly_demo else
         {'id': 'anomaly_detection', 'status': 'unavailable',
          'message': 'A validated anomaly-detection capability is not deployed; existing deterministic checks remain active.'}),
        {'id': 'scrutiny_assistance', 'status': 'available',
         'message': 'Existing case-age, workflow-state, and deadline rules provide advisory review priority.'},
    ]}
=======

router = APIRouter()
ADMIN = require_roles(Role.ADMIN)
>>>>>>> a27ee110f6ba3d79cb2eb0cff239996b7f97ea26


@router.get('/operations/health')
async def operations_health(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.admin_ops_service import generate_health_report
    return await generate_health_report(session)


@router.get('/operations/failed-jobs')
async def operations_failed_jobs(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.admin_ops_service import get_failed_jobs
    return await get_failed_jobs(session)


@router.get('/operations/stuck-cases')
async def operations_stuck_cases(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.admin_ops_service import get_stuck_cases
    return await get_stuck_cases(session)


@router.get('/operations/delivery-failures')
async def operations_delivery_failures(hours: int = 24, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    if hours < 1 or hours > 720:
        raise HTTPException(422, 'hours must be between 1 and 720')
    from app.services.admin_ops_service import get_delivery_failures
    return await get_delivery_failures(session, hours)


@router.get('/operations/recovery-recommendations')
async def operations_recovery_recommendations(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.admin_ops_service import recommend_recovery
    return await recommend_recovery(session)


@router.post('/operations/actions/{action}')
async def operations_safe_action(action: str, body: dict = Body(...), session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.admin_ops_service import requeue_failed_job, send_test_alert
    confirmed = body.get('confirmed') is True
    if action == 'requeue-failed-job':
        try:
            outbox_id = int(body.get('outbox_id'))
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, 'outbox_id must be an integer') from exc
        return await requeue_failed_job(session, actor, outbox_id, confirmed)
    if action == 'send-test-alert':
        channel = body.get('channel', 'email')
        recipient = body.get('recipient', actor.email)
        if channel not in {'email', 'telegram', 'whatsapp_mock'} or not isinstance(recipient, str) or not recipient.strip():
            raise HTTPException(422, 'A supported channel and non-empty recipient are required')
        return await send_test_alert(session, actor, channel, recipient.strip(), confirmed)
    raise HTTPException(404, 'Unsupported operations action')


@router.get('/rules')
async def list_automation_rules(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.admin_rules_service import list_rules
    return await list_rules(session)


@router.post('/rules', status_code=201)
async def create_automation_rule(body: dict = Body(...), session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.admin_rules_service import create_rule
    return await create_rule(session, actor, body.get('rule_key', ''), body.get('description', ''), body.get('policy'))


@router.post('/rules/{rule_id}/versions', status_code=201)
async def create_automation_rule_version(rule_id: int, body: dict = Body(...),
                                         session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.admin_rules_service import append_version
    return await append_version(session, actor, rule_id, body.get('policy'))


@router.get('/ml/gates')
async def ml_gate_status(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.ml_service import assess_gates
    return await assess_gates(session)


@router.post('/ml/gates/evaluate')
async def ml_evaluate_gates(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.ml_service import register_gate_evaluation
    return await register_gate_evaluation(session, actor)


@router.post('/ml/demo-data')
async def ml_generate_demo_data(body: dict = Body(default={}), session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.ml_service import generate_synthetic_demo_data
    return await generate_synthetic_demo_data(session, actor, body.get('count', 200), body.get('seed', 202613))


@router.get('/ml/registry')
async def ml_registry(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.ml_service import list_registry
    return await list_registry(session)


@router.get('/ml/demo-samples')
async def ml_demo_samples(limit: int = 100, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    if limit < 1 or limit > 1000: raise HTTPException(422, 'limit must be between 1 and 1000')
    from app.services.ml_service import list_demo_samples
    return await list_demo_samples(session, limit)


@router.get('/ml/predictions')
async def ml_predictions(is_synthetic: bool | None = None, limit: int = 100,
                         session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    if limit < 1 or limit > 1000: raise HTTPException(422, 'limit must be between 1 and 1000')
    from app.services.ml_service import list_predictions
    return await list_predictions(session, is_synthetic, limit)


@router.post('/ml/predictions/run')
async def ml_run_fallbacks(body: dict = Body(default={}), idempotency_key: str = Header(...,alias='Idempotency-Key',min_length=8,max_length=255),
                           session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.ml_service import run_fallback_predictions
    return await run_fallback_predictions(session, actor, body.get('use_case', 'all'), body.get('limit', 100), idempotency_key)


@router.get('/audit/verify-chain')
async def verify_audit_hash_chain(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.audit_service import verify_audit_chain
    return await verify_audit_chain(session)


@router.get('/audit/export')
async def export_audit_hash_chain(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.services.audit_service import export_audit_chain
    return await export_audit_chain(session)


@router.get('/users', response_model=list[AdminUserOut])
async def list_users(role: str | None = None, status: str | None = None, q: str | None = None,
                     page: Pagination = Depends(pagination), session: AsyncSession = Depends(get_session),
                     actor=Depends(ADMIN)):
    return await user_admin_service.list_users(session, role, status, q, page)


@router.post('/users', response_model=AdminUserOut, status_code=201)
async def create_user(body: AdminUserCreate, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    try: return await user_admin_service.create_user(session, body, actor)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.patch('/users/{user_id}', response_model=AdminUserOut)
async def update_user(user_id: int, body: AdminUserUpdate, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    try: return await user_admin_service.update_user(session, user_id, body, actor)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post('/users/{user_id}/disable', response_model=AdminUserOut)
async def disable_user(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.set_user_active(session, user_id, False, actor)


@router.post('/users/{user_id}/enable', response_model=AdminUserOut)
async def enable_user(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.set_user_active(session, user_id, True, actor)


@router.post('/users/{user_id}/suspend', response_model=AdminUserOut)
async def suspend_user(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.suspend_user(session, user_id, actor)


@router.post('/users/{user_id}/unlock', response_model=AdminUserOut)
async def unlock_user(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.unlock_user(session, user_id, actor)


@router.post('/users/{user_id}/reset-password', status_code=202)
async def reset_user_password(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    await user_admin_service.reset_user_password(session, user_id, actor)
    return {'queued': True}


@router.post('/users/{user_id}/revoke-sessions', status_code=204)
async def revoke_sessions(user_id: int, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    await user_admin_service.revoke_sessions(session, user_id, actor)


@router.get('/registrations', response_model=list[AdminUserOut])
async def pending_registrations(include_decided: bool = False, page: Pagination = Depends(pagination),
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    if include_decided:
        return await user_admin_service.list_institution_registration_history(session, page)
    return await user_admin_service.list_pending_registrations(session, Role.INSTITUTION.value, page)


@router.post('/registrations/{user_id}/approve', response_model=AdminUserOut)
async def approve_registration(user_id: int, body: RegistrationDecision | None = None,
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.approve_registration(session, user_id, True, body.reason if body else None, actor)


@router.post('/registrations/{user_id}/reject', response_model=AdminUserOut)
async def reject_registration(user_id: int, body: RegistrationDecision, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    if not body.reason:
        raise HTTPException(422, 'A rejection reason is required.')
    return await user_admin_service.approve_registration(session, user_id, False, body.reason, actor)


@router.get('/official-registrations', response_model=list[AdminUserOut])
async def pending_official_registrations(include_decided: bool = False, page: Pagination = Depends(pagination),
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.list_pending_registrations(session, Role.AICTE_OFFICIAL.value, page,
        include_decided=include_decided)


@router.post('/official-registrations/{user_id}/approve', response_model=AdminUserOut)
async def approve_official_registration(user_id: int, body: RegistrationDecision | None = None,
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.decide_registration(session, user_id, True, body.reason if body else None, actor)


@router.post('/official-registrations/{user_id}/reject', response_model=AdminUserOut)
async def reject_official_registration(user_id: int, body: RegistrationDecision, session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    if not body.reason:
        raise HTTPException(422, 'A rejection reason is required.')
    return await user_admin_service.decide_registration(session, user_id, False, body.reason, actor)


@router.post('/official-registrations/{user_id}/override', response_model=AdminUserOut)
async def override_official_registration(user_id: int, body: RegistrationDecisionRequest,
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.decide_registration(session, user_id,
        body.decision == 'approve', body.reason, actor, override=True)


@router.post('/registrations/{user_id}/override', response_model=AdminUserOut)
async def override_institution_registration(user_id: int, body: RegistrationDecisionRequest,
        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    return await user_admin_service.decide_registration(session, user_id,
        body.decision == 'approve', body.reason, actor, override=True)


@router.get('/notification-deliveries')
async def notification_deliveries(status: str | None = None, page: Pagination = Depends(pagination),
                                  session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    query = select(NotificationDeliveryAttempt).order_by(NotificationDeliveryAttempt.scheduled_at.desc())
    if status: query = query.where(NotificationDeliveryAttempt.status == status)
    attempts = list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
    result=[]
    for attempt in attempts:
        notification = await session.get(Notification, attempt.notification_id)
        result.append({'attempt_id':attempt.id,'notification_id':attempt.notification_id,
            'fdr_id':notification.fdr_id if notification else None,
            'stage':notification.stage if notification else None,'channel':attempt.provider,
            'recipient':notification.recipient if notification else None,'status':attempt.status,
            'attempt_no':attempt.attempt_no,'template_version':attempt.template_version,
            'scheduled_at':attempt.scheduled_at,'sent_at':attempt.sent_at,'error':attempt.error})
    return result


@router.get('/outbox')
async def outbox_status(status: str | None = None, page: Pagination = Depends(pagination),
                        session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    query=select(OutboxEvent).order_by(OutboxEvent.created_at.desc())
    if status: query=query.where(OutboxEvent.status==status)
    rows=list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
    return [{'id':row.id,'aggregate_id':row.aggregate_id,'event_type':row.event_type,
        'status':row.status,'attempts':row.attempts,'next_attempt_at':row.next_attempt_at,
        'locked_until':row.locked_until,'last_error':row.last_error,'created_at':row.created_at} for row in rows]


@router.get('/workflow-health')
async def workflow_health(session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from sqlalchemy import func
    from app.models.workflow import WorkflowInstance
    by_execution=dict((await session.execute(select(WorkflowInstance.execution_state,
        func.count(WorkflowInstance.id)).group_by(WorkflowInstance.execution_state))).all())
    dead_outbox=await session.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status=='dead'))
    pending_outbox=await session.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status.in_(['pending','failed','processing'])))
    return {'workflow_counts':by_execution,'outbox_dead':int(dead_outbox or 0),
        'outbox_pending_or_processing':int(pending_outbox or 0)}


@router.get('/workflow-failures')
async def workflow_failures(page: Pagination = Depends(pagination), session: AsyncSession = Depends(get_session), actor=Depends(ADMIN)):
    from app.models.workflow import WorkflowInstance, WorkflowNodeExecution
    rows=(await session.execute(select(WorkflowInstance,WorkflowNodeExecution)
        .join(WorkflowNodeExecution,WorkflowNodeExecution.workflow_instance_id==WorkflowInstance.id)
        .where(WorkflowInstance.execution_state.in_(['blocked','failed']),WorkflowNodeExecution.status=='failed')
        .order_by(WorkflowNodeExecution.finished_at.desc()).offset(page.skip).limit(page.limit))).all()
    return [{'workflow_id':workflow.id,'fdr_id':workflow.fdr_id,'node_execution_id':node.id,
        'node_key':node.node_key,'error_class':node.error_class,'error_code':node.error_code,
        'error_message':node.error_message,'finished_at':node.finished_at} for workflow,node in rows]
