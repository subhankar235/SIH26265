"""Periodic raw metric capture for the BOCPD Gate 0 series."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.database import SessionLocal
from sqlalchemy import select
from app.services.admin_ops_service import collect_operations_metrics
from app.services.ml_service import capture_operations_snapshot
from app.workers.celery_app import celery_app, run_async_task


@celery_app.task(name='app.workers.tasks_ml.capture_operations_snapshot')
def capture_operations_snapshot_task() -> dict:
    return run_async_task(_capture())


@celery_app.task(name='app.workers.tasks_ml.train_review_priority', acks_late=True, track_started=True)
def train_review_priority_task(dataset_path: str, dataset_reference: str, random_seed: int,
                               requested_by_id: int, job_id: int) -> dict:
    """Train/evaluate a candidate and persist job, artifact registry, and audit state."""
    return run_async_task(_train_review_priority(dataset_path, dataset_reference, random_seed,
                                                 requested_by_id, job_id))


async def _train_review_priority(dataset_path: str, dataset_reference: str, random_seed: int,
                                requested_by_id: int, job_id: int) -> dict:
    from app.core.intelligence_config import get_intelligence_settings
    from app.services.intelligence_training import read_training_csv, train_and_evaluate
    from app.models.ml import MLModelVersion, MLTrainingJob
    from app.services.audit_service import record

    settings = get_intelligence_settings()
    dataset = Path(dataset_path).resolve()
    root = Path(settings.artifact_path).resolve()
    if root not in dataset.parents or dataset.suffix.lower() != '.csv':
        raise ValueError('Training input must be a CSV inside the configured private artifact directory.')
    try:
        async with SessionLocal() as session:
            job = await session.get(MLTrainingJob, job_id)
            if not job:
                raise ValueError('Training job record no longer exists.')
            previous = job.status
            job.status = 'RUNNING'
            await record(session, requested_by_id, 'ml_training_job', job.id, 'TRAINING_STARTED', 'worker',
                         {'status': [previous, 'RUNNING']}, actor_type='system')
            await session.commit()
        rows = read_training_csv(dataset)
        result = train_and_evaluate(rows, random_seed=random_seed, dataset_reference=dataset_reference)
        from app.integrations import storage_client
        artifact_dir = Path(result['artifact_dir'])
        metadata_path = artifact_dir / 'metadata.json'
        metadata = __import__('json').loads(metadata_path.read_text(encoding='utf-8'))
        artifact_prefix = f"{settings.artifact_storage_prefix.strip('/')}/{result['artifact_version']}"
        artifact_key = f'{artifact_prefix}/review-priority.joblib'
        metadata_key = f'{artifact_prefix}/metadata.json'
        storage_client.put(artifact_key, (artifact_dir / 'review-priority.joblib').read_bytes(),
                           'application/octet-stream')
        metadata.update({'artifact_storage_key': artifact_key, 'metadata_storage_key': metadata_key})
        metadata_path.write_text(__import__('json').dumps(metadata, indent=2), encoding='utf-8')
        storage_client.put(metadata_key, metadata_path.read_bytes(), 'application/json')
        async with SessionLocal() as session:
            job = await session.get(MLTrainingJob, job_id)
            if not job:
                raise ValueError('Training job record no longer exists after evaluation.')
            model_version = MLModelVersion(use_case='review_priority', version=result['artifact_version'],
                model_name='LogisticRegression', status='CANDIDATE', feature_version='review-priority-v1',
                seed=random_seed, dataset_hash=metadata['dataset_sha256'], training_rows=len(rows),
                real_training_rows=len(rows) if metadata['origin'] == 'real' else 0,
                synthetic_training_rows=len(rows) if metadata['origin'] == 'synthetic' else 0,
                evaluation_metrics=result['metrics'],
                acceptance_criteria=result['metrics']['acceptance_criteria'],
                library_versions={'artifact_storage_key': artifact_key,
                    'metadata_storage_key': metadata_key,
                    'scikit_learn': __import__('sklearn').__version__},
                fallback_name='configured_ollama_review_assessment', is_synthetic=metadata['origin'] == 'synthetic')
            session.add(model_version)
            job.status = 'COMPLETED'
            job.evaluation_metrics = result['metrics']
            job.artifact_version = result['artifact_version']
            await session.flush()
            await record(session, requested_by_id, 'ml_training_job', job.id, 'TRAINING_COMPLETED', 'worker',
                         {'status': ['RUNNING', 'COMPLETED'], 'artifact_version': [None, job.artifact_version],
                          'evaluation_passed': [None, result['evaluation_passed']]}, actor_type='system')
            await record(session, requested_by_id, 'ml_model_version', model_version.id, 'MODEL_CANDIDATE_CREATED',
                         'worker', {'status': [None, model_version.status],
                         'dataset_hash': [None, model_version.dataset_hash]}, actor_type='system')
            await session.commit()
        return {key: value for key, value in result.items() if key != 'artifact_dir'}
    except Exception as exc:
        async with SessionLocal() as session:
            job = await session.get(MLTrainingJob, job_id)
            if job:
                previous = job.status
                job.status = 'FAILED'
                job.error_summary = f'{type(exc).__name__}: {str(exc)[:450]}'
                await record(session, requested_by_id, 'ml_training_job', job.id, 'TRAINING_FAILED', 'worker',
                             {'status': [previous, 'FAILED'], 'error_class': [None, type(exc).__name__]},
                             actor_type='system')
                await session.commit()
        raise
    finally:
        dataset.unlink(missing_ok=True)


@celery_app.task(name='app.workers.tasks_ml.reconcile_stale_training_jobs')
def reconcile_stale_training_jobs_task() -> dict:
    return run_async_task(_reconcile_stale_training_jobs())


async def _reconcile_stale_training_jobs() -> dict:
    from app.core.intelligence_config import get_intelligence_settings
    from app.models.ml import MLTrainingJob
    from app.services.audit_service import record

    settings = get_intelligence_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.training_job_stale_minutes)
    async with SessionLocal() as session:
        rows = list((await session.scalars(select(MLTrainingJob).where(
            MLTrainingJob.status.in_(['QUEUED', 'RUNNING']),
            MLTrainingJob.updated_at < cutoff).order_by(MLTrainingJob.updated_at)
            .with_for_update(skip_locked=True).limit(100))).all())
        for job in rows:
            previous = job.status
            job.status = 'FAILED'
            job.error_summary = 'Training worker did not complete before the configured stale-job limit.'
            await record(session, None, 'ml_training_job', job.id, 'TRAINING_JOB_STALE', 'scheduler',
                {'status': [previous, 'FAILED'], 'error_code': [None, 'TRAINING_JOB_STALE']},
                actor_type='system')
        await session.commit()
    incoming = Path(settings.artifact_path).resolve() / 'incoming'
    deleted_files = 0
    for job in rows:
        for file in incoming.glob(f'{job.id}-*.csv'):
            file.unlink(missing_ok=True)
            deleted_files += 1
    return {'failed_jobs': len(rows), 'deleted_uploads': deleted_files}


async def _capture() -> dict:
    async with SessionLocal() as session:
        metrics=await collect_operations_metrics(session)
        # Development/test metrics include demo-seeded activity and never qualify as
        # real training observations. Production snapshots are still raw measurements.
        synthetic=get_settings().app_env.lower() in {'dev','development','test'}
        row=await capture_operations_snapshot(session,metrics,is_synthetic=synthetic)
        await session.commit()
        return {'snapshot_id':row.id,'is_synthetic':synthetic,'captured_at':row.captured_at.isoformat()}
