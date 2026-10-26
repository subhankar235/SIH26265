"""Durable workflow worker and transactional-outbox dispatcher."""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import select, func
from app.core.database import SessionLocal
from .celery_app import celery_app, run_async_task
from app.core.enums import (AuthorizationState, ExecutionState, FDRStatus, TrustBadge,
    LifecycleState, VerificationLevel)
from app.models.discrepancy import Discrepancy
from app.models.document import Document
from app.models.fdr import FDR
from app.models.institution import Institution
from app.models.notification import Notification
from app.models.user import User
from app.models.workflow import (CorrectionRequest, ExceptionItem,
    CommandExecution, VerificationRun, WorkflowCheckpoint, WorkflowEvent,
    WorkflowInstance, WorkflowNodeExecution)
from app.services import bank_verification_service, fraud_service, ocr_service, trust_score_service
from app.services.validation_service import make_extraction_result, validate_fdr
from app.services.audit_service import record
from app.services.outbox_service import dispatch_batch as dispatch_outbox_batch
from app.services.outbox_service import enqueue as enqueue_outbox
from app.services.workflow_events import publish
from app.workflows.definition import NODES, START_NODE, WORKFLOW_VERSION, next_node
from app.workflows.transitions import transition as workflow_transition
from app.integrations import storage_client

logger = logging.getLogger(__name__)
MAX_NODE_FAILURES = 8
LEASE_SECONDS = 240


class InputFailure(Exception): pass
class TransientFailure(Exception): pass


def _utcnow(): return datetime.now(timezone.utc)
def _aware(dt): return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


@celery_app.task(name='app.workers.tasks_workflow.dispatch_outbox')
def dispatch_outbox_task() -> dict:
    return run_async_task(_dispatch_outbox())


async def _dispatch_outbox():
    async with SessionLocal() as session:
        result = await dispatch_outbox_batch(session)
        await session.commit()
        return result


@celery_app.task(name='app.workers.tasks_workflow.process_workflow', acks_late=True)
def process_workflow(workflow_instance_id: int) -> None:
    run_async_task(_process_workflow(workflow_instance_id))


@celery_app.task(name='app.workers.tasks_workflow.process_command',acks_late=True)
def process_command(command_id: int) -> None:
    run_async_task(_process_command(command_id))


async def _process_command(command_id: int):
    from app.services.command_service import execute
    try:
        async with SessionLocal() as session:
            await execute(session,command_id)
            await session.commit()
    except Exception as exc:
        logger.exception('Command execution failed command=%s',command_id)
        async with SessionLocal() as session:
            command=await session.get(CommandExecution,command_id)
            if command and command.status in {'confirmed','running'}:
                previous=command.status;command.status='failed'
                command.result_summary=f'Execution failed safely: {type(exc).__name__}: {exc}'[:4000]
                await record(session,command.user_id,'command',command.id,'COMMAND_FAILED','worker',
                    {'status':[previous,'failed'],'error':[None,command.result_summary]},actor_type='system')
                await session.commit()


@celery_app.task(name='app.workers.tasks_workflow.recover_expired_leases')
def recover_expired_leases() -> int:
    return run_async_task(_recover_expired_leases())


async def _recover_expired_leases() -> int:
    """Requeue only executions whose worker lease expired; dedupe is DB-enforced."""
    now = _utcnow()
    async with SessionLocal() as session:
        rows = list((await session.scalars(select(WorkflowInstance).where(
            WorkflowInstance.execution_state.in_([ExecutionState.RUNNING.value, ExecutionState.RETRYING.value]),
            WorkflowInstance.worker_lease_until.is_not(None),
            WorkflowInstance.worker_lease_until <= now).with_for_update(skip_locked=True).limit(100))).all())
        for instance in rows:
            running_nodes = list((await session.scalars(select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_instance_id == instance.id,
                WorkflowNodeExecution.status == 'running'))).all())
            for node in running_nodes:
                node.status = 'failed'; node.finished_at = now
                node.error_class = 'WORKER_LOST'; node.error_code = 'LEASE_EXPIRED'
                node.error_message = 'Worker lease expired; operation will be retried.'
                await record(session, None, 'workflow_node_execution', node.id, 'WORKER_LOST', 'scheduler',
                    {'status': ['running','failed'], 'error_code': [None,'LEASE_EXPIRED']},
                    actor_type='system', institution_id=instance.institution_id)
            instance.execution_state = ExecutionState.RETRYING.value
            instance.worker_lease_until = None
            await enqueue_outbox(session, str(instance.id), 'WORKFLOW_WAKE',
                {'workflow_instance_id': instance.id, 'recovered_lease': True},
                f'workflow:{instance.id}:version:{instance.version}:lease-recovery:{int(now.timestamp())}')
            await record(session, None, 'workflow', instance.id, 'WORKER_LEASE_EXPIRED', 'scheduler',
                {'execution_state': [ExecutionState.RUNNING.value, ExecutionState.RETRYING.value]},
                actor_type='system', institution_id=instance.institution_id)
        timers = list((await session.scalars(select(WorkflowInstance).where(
            WorkflowInstance.execution_state == ExecutionState.WAITING_EVENT.value,
            WorkflowInstance.next_wake_at.is_not(None), WorkflowInstance.next_wake_at <= now)
            .with_for_update(skip_locked=True).limit(100))).all())
        for instance in timers:
            correction = await session.scalar(select(CorrectionRequest).where(
                CorrectionRequest.workflow_instance_id == instance.id,
                CorrectionRequest.status == 'open').order_by(CorrectionRequest.id.desc()).limit(1))
            if not correction: continue
            lifecycle, execution = workflow_transition(instance, 'TIMER_FIRED')
            correction.status = 'expired'; correction.responded_at = now
            instance.lifecycle_state = lifecycle; instance.execution_state = execution
            instance.next_wake_at = None; instance.worker_lease_until = None
            instance.version += 1
            fdr = await session.get(FDR, instance.fdr_id)
            if fdr:
                fdr.lifecycle_state = lifecycle; fdr.execution_state = execution
                await record(session, None, 'fdr', fdr.id, 'CORRECTION_SLA_ESCALATED', 'scheduler',
                    {'lifecycle_state': [LifecycleState.AWAITING_INSTITUTION.value, lifecycle]},
                    actor_type='system', institution_id=instance.institution_id)
                officials = list((await session.scalars(select(User.email).where(
                    User.role == 'aicte_official', User.is_active.is_(True)))).all())
                stage = f'CORRECTION-SLA-{correction.id}'
                if officials and not await session.scalar(select(Notification.id).where(
                    Notification.fdr_id == fdr.id, Notification.stage == stage, Notification.channel == 'email')):
                    recipients = ', '.join(officials)
                    notification = Notification(fdr_id=fdr.id, stage=stage, channel='email',
                        recipient=recipients, status='queued')
                    session.add(notification); await session.flush()
                    await enqueue_outbox(session, str(fdr.id), 'DELIVER_NOTIFICATION',
            {'notification_id':notification.id,'channel':'email','recipient':recipients,
                         'subject':f'FDR correction overdue: {fdr.fdr_number}',
                         'body':f'<p>Correction request {correction.id} is overdue for FDR {fdr.fdr_number}.</p>',
                         'template_version':'correction-sla-v1'},
                        f'correction-sla:{correction.id}:official-alert')
            await publish(session, instance.id, 'CORRECTION_SLA_EXPIRED',
                {'correction_request_id': correction.id}, f'correction:{correction.id}:sla-expired')
            await record(session, None, 'workflow', instance.id, 'CORRECTION_SLA_EXPIRED', 'scheduler',
                {'execution_state': [ExecutionState.WAITING_EVENT.value, execution]},
                actor_type='system', institution_id=instance.institution_id)
        await session.commit()
        return len(rows) + len(timers)


async def _claim_next_node(workflow_id: int):
    now = _utcnow()
    async with SessionLocal() as session:
        instance = await session.scalar(select(WorkflowInstance).where(
            WorkflowInstance.id == workflow_id).with_for_update())
        if not instance or instance.execution_state in {
            ExecutionState.PAUSED.value, ExecutionState.WAITING_EVENT.value,
            ExecutionState.WAITING_TIMER.value, ExecutionState.WAITING_HUMAN.value,
            ExecutionState.BLOCKED.value, ExecutionState.CANCELLED.value,
            ExecutionState.COMPLETED.value, ExecutionState.FAILED.value}:
            await session.commit(); return None
        if instance.worker_lease_until and _aware(instance.worker_lease_until) > now:
            await session.commit(); return None
        if instance.worker_lease_until:
            expired_node = await session.scalar(select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_instance_id == instance.id,
                WorkflowNodeExecution.node_key == instance.current_node,
                WorkflowNodeExecution.status == 'running').order_by(WorkflowNodeExecution.attempt.desc()).limit(1))
            if expired_node:
                expired_node.status = 'failed'; expired_node.finished_at = now
                expired_node.error_class = 'WORKER_LOST'; expired_node.error_code = 'LEASE_EXPIRED'
                expired_node.error_message = 'Workflow task was redelivered after its lease expired.'
        if instance.execution_state == ExecutionState.NOT_STARTED.value:
            lifecycle, execution = workflow_transition(instance, 'START')
            if lifecycle: instance.lifecycle_state = lifecycle
            instance.execution_state = execution
            instance.current_node = START_NODE
        elif instance.execution_state == ExecutionState.RETRYING.value:
            _, instance.execution_state = workflow_transition(instance, 'RETRY')
        if instance.execution_state == ExecutionState.RUNNING.value:
            _, instance.execution_state = workflow_transition(instance, 'NODE_STARTED')
        node = instance.current_node or START_NODE
        if node not in NODES:
            instance.execution_state = ExecutionState.BLOCKED.value
            instance.worker_lease_until = None
            await record(session, None, 'workflow', instance.id, 'UNKNOWN_WORKFLOW_NODE', 'worker',
                {'node': [None, node]}, actor_type='system', institution_id=instance.institution_id)
            await session.commit(); return None
        prior = list((await session.scalars(select(WorkflowNodeExecution).where(
            WorkflowNodeExecution.workflow_instance_id == instance.id,
            WorkflowNodeExecution.node_key == node).order_by(WorkflowNodeExecution.attempt))).all())
        attempt = len(prior) + 1
        latest_document = await session.get(Document, instance.replay_document_id) if instance.replay_document_id else None
        if latest_document is None:
            latest_document = await session.scalar(select(Document).where(
                Document.fdr_id == instance.fdr_id, Document.doc_type == 'fdr_scan')
                .order_by(Document.version_no.desc(), Document.id.desc()))
        input_ref = instance.retry_input_ref or {'fdr_id': instance.fdr_id,
            'document_id': latest_document.id if latest_document else None,
            'document_version': latest_document.version_no if latest_document else None,
            'document_sha256': latest_document.sha256 if latest_document else None}
        input_hash = hashlib.sha256(json.dumps(input_ref, sort_keys=True).encode()).hexdigest()
        run = WorkflowNodeExecution(workflow_instance_id=instance.id, node_key=node, attempt=attempt,
            status='running', started_at=now, workflow_version=instance.workflow_version,
            triggered_by='user' if instance.replay_requested_by else 'system', input_ref=input_ref, input_hash=input_hash,
            idempotency_key=f'workflow:{instance.id}:execution:{instance.execution_version}:node:{node}:attempt:{attempt}',
            parent_execution_id=instance.retry_parent_execution_id or (prior[-1].id if prior else None),
            replay_of_id=instance.replay_from_execution_id,
            actor_user_id=instance.replay_requested_by, reason=instance.replay_reason)
        instance.current_node = node
        instance.replay_from_execution_id = None
        instance.replay_requested_by = None
        instance.replay_reason = None
        instance.retry_input_ref = None
        instance.retry_parent_execution_id = None
        instance.worker_lease_until = now + timedelta(seconds=LEASE_SECONDS)
        instance.updated_at = now
        instance.version += 1
        session.add(run)
        await session.flush()
        await record(session, None, 'workflow_node_execution', run.id, 'NODE_STARTED', 'worker',
            {'node_key': [None, node], 'attempt': [None, attempt]}, actor_type='system',
            institution_id=instance.institution_id)
        await publish(session,instance.id,'node.started',{'node_execution_id':run.id,
            'node_key':node,'attempt':attempt},f'workflow-node:{run.id}:started')
        await session.commit()
        return {'run_id': run.id, 'workflow_id': instance.id, 'fdr_id': instance.fdr_id,
            'institution_id': instance.institution_id, 'node': node, 'attempt': attempt,
            'workflow_version': instance.workflow_version,
            'replay_document_id': input_ref.get('document_id'),
            'replay_of_id': run.replay_of_id}


async def _execute_node(claim: dict) -> tuple[dict, str | None]:
    async with SessionLocal() as session:
        fdr = await session.get(FDR, claim['fdr_id'])
        if not fdr: raise InputFailure('FDR record no longer exists')
        if claim['node'] == 'extract_document':
            doc = await session.get(Document, claim.get('replay_document_id')) if claim.get('replay_document_id') else None
            if doc is None:
                doc = await session.scalar(select(Document).where(Document.fdr_id == fdr.id,
                    Document.doc_type == 'fdr_scan').order_by(Document.version_no.desc(), Document.id.desc()))
            if not doc: raise InputFailure('No FDR scan is available for extraction')
            try:
                data = await asyncio.to_thread(storage_client.get, doc.s3_key)
            except (TimeoutError, ConnectionError, OSError) as exc:
                raise TransientFailure(f'Document storage temporarily unavailable: {exc}') from exc
            try:
                extracted = await ocr_service.extract_fdr_fields(data, doc.content_type, raise_errors=True)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise TransientFailure(f'OCR service temporarily unavailable: {exc}') from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 or exc.response.status_code >= 500:
                    raise TransientFailure(f'OCR provider HTTP {exc.response.status_code}') from exc
                raise
            except (ValueError, OSError, ImportError) as exc:
                raise InputFailure(f'Document could not be extracted: {exc}') from exc
            source_spans=await ocr_service.extract_source_spans(data,doc.content_type,
                extracted.model_dump(mode='json',exclude={'confidence'}))
            fdr.ocr_data = extracted.model_dump(mode='json')
            settings=__import__('app.core.config', fromlist=['get_settings']).get_settings()
            extraction_result=make_extraction_result(fdr,doc,extracted,
                settings.ollama_model if settings.ocr_engine=='ollama_vision' else settings.ocr_engine,
                source_spans=source_spans)
            session.add(VerificationRun(fdr_id=fdr.id,document_id=doc.id,
                extraction_engine=settings.ocr_engine,
                engine_version=settings.ollama_model if settings.ocr_engine=='ollama_vision' else settings.ocr_engine,
                source='ocr_extraction',verification_level=VerificationLevel.EXTRACTED.value,
                idempotency_key=f"workflow:{claim['workflow_id']}:node:extract_document:attempt:{claim['attempt']}",
                declared_snapshot=fdr.declared_data or {},
                extracted_fields=extraction_result.model_dump(mode='json'),bank_result=None,
                discrepancies=[],confidence=float(extracted.confidence)))
            output = {'document_id': doc.id, 'document_sha256': doc.sha256,
                      'confidence': float(extracted.confidence),
                      'extraction_result': extraction_result.model_dump(mode='json')}
            await record(session, None, 'fdr', fdr.id, 'DOCUMENT_EXTRACTED', 'workflow-worker',
                {'document_id': [None, doc.id], 'confidence': [None, float(extracted.confidence)]},
                actor_type='system', institution_id=fdr.institution_id)
            if extracted.confidence <= 0:
                await session.commit()
                return output, 'correction'
            fdr.verification_level = VerificationLevel.EXTRACTED.value
            await session.commit()
            return output, None

        if claim['node'] == 'validate_fields':
            from app.schemas.verification import OcrResult
            doc = await session.get(Document, claim.get('replay_document_id')) if claim.get('replay_document_id') else None
            if doc is None:
                doc = await session.scalar(select(Document).where(Document.fdr_id == fdr.id,
                    Document.doc_type == 'fdr_scan').order_by(Document.version_no.desc(), Document.id.desc()))
            if not doc: raise InputFailure('No FDR document version is available to validate')
            if claim.get('replay_of_id'):
                extraction_run = await session.scalar(select(VerificationRun).where(
                    VerificationRun.fdr_id == fdr.id, VerificationRun.document_id == doc.id,
                    VerificationRun.source == 'ocr_extraction').order_by(VerificationRun.created_at.desc()).limit(1))
                if not extraction_run:
                    raise InputFailure('Replay checkpoint has no preserved OCR extraction result for its document version')
                from app.schemas.workflow import ExtractionResult
                preserved = ExtractionResult.model_validate(extraction_run.extracted_fields)
                values = {key: field.value for key,field in preserved.fields.items()}
                values['holder_name'] = values.pop('holder', None)
                values['confidence'] = preserved.overall_confidence
                extracted = OcrResult.model_validate(values)
            else:
                extracted = OcrResult.model_validate(fdr.ocr_data or {})
            settings=__import__('app.core.config', fromlist=['get_settings']).get_settings()
            extraction_result=make_extraction_result(fdr,doc,extracted,
                settings.ollama_model if settings.ocr_engine=='ollama_vision' else settings.ocr_engine)
            # Authenticity rejection (and unreadable pages) stays in the submitted/yellow queue.
            if extracted.confidence <= 0:
                fdr.trust_badge = TrustBadge.SELF_DECLARED.value
                await session.commit()
                return {'confidence': 0, 'extraction_result': extraction_result.model_dump(mode='json')}, 'human_review'
            validation = await validate_fdr(session,fdr,extraction_result)
            bank = await bank_verification_service.verify_with_bank(
                fdr.bank_name, fdr.fdr_number, fdr.declared_data.get('holder', ''))
            fdr.bank_data = bank.model_dump(mode='json')
            if bank.found:
                fdr.verification_level = VerificationLevel.MOCK_VERIFIED.value
            items = await fraud_service.compare_records(fdr.declared_data, extracted, bank)
            await fraud_service.persist_discrepancies(session, fdr.id, items, validation.discrepancies)
            await trust_score_service.apply_badge(session, fdr.id, persist_workflow_event=False)
            run_key = f"workflow:{claim['workflow_id']}:node:validate_fields:attempt:{claim['attempt']}"
            session.add(VerificationRun(fdr_id=fdr.id, document_id=doc.id if doc else None,
                extraction_engine=settings.ocr_engine,
                source='mock_bank_gateway' if bank.found else 'mock_bank_unavailable',
                verification_level=VerificationLevel.MOCK_VERIFIED.value if bank.found else VerificationLevel.EXTRACTED.value,
                idempotency_key=run_key, declared_snapshot=fdr.declared_data,
                extracted_fields=extracted.model_dump(mode='json'), bank_result=bank.model_dump(mode='json'),
                discrepancies=[item.model_dump(mode='json') for item in items] +
                    [item.model_dump(mode='json') for item in validation.discrepancies],
                confidence=float(extracted.confidence)))
            unresolved_high = [item for item in items if item.severity == 'high']
            unresolved_high.extend(item for item in validation.discrepancies if item.severity == 'high')
            output = {'bank_found': bool(bank.found), 'verification_source': 'mock' if bank.found else 'none',
                'validation_result': validation.model_dump(mode='json'),
                'discrepancy_count': len(items) + len(validation.discrepancies),
                'high_discrepancy_count': len(unresolved_high)}
            await session.commit()
            return output, 'correction' if unresolved_high else None

        if claim['node'] == 'route_case':
            high_rows = list((await session.scalars(select(Discrepancy).where(
                Discrepancy.fdr_id == fdr.id, Discrepancy.resolved.is_(False),
                Discrepancy.severity == 'high'))).all())
            return {'route': 'correction' if high_rows else 'human_review',
                'high_discrepancy_count': len(high_rows),
                'discrepancy_ids': [row.id for row in high_rows]}, 'correction' if high_rows else 'human_review'

        raise InputFailure(f'No executor registered for workflow node {claim["node"]}')


async def _finish_node(claim: dict, output: dict, branch: str | None):
    now = _utcnow()
    async with SessionLocal() as session:
        instance = await session.scalar(select(WorkflowInstance).where(
            WorkflowInstance.id == claim['workflow_id']).with_for_update())
        node = await session.get(WorkflowNodeExecution, claim['run_id'])
        if not instance or not node or node.status != 'running':
            await session.commit(); return
        node.status = 'succeeded'; node.output_ref = output; node.finished_at = now
        node.duration_ms = max(0, int((now - _aware(node.started_at)).total_seconds() * 1000))
        state = {**(node.input_ref or {}), 'output': output, 'branch': branch,
                 'workflow_version': instance.workflow_version}
        session.add(WorkflowCheckpoint(workflow_instance_id=instance.id,
            node_execution_id=node.id, schema_version=1, state_snapshot=state))
        await record(session, None, 'workflow_node_execution', node.id, 'NODE_SUCCEEDED', 'worker',
            {'status': ['running','succeeded'], 'output': output}, actor_type='system',
            institution_id=instance.institution_id)
        await publish(session,instance.id,'node.succeeded',{'node_execution_id':node.id,
            'node_key':node.node_key,'attempt':node.attempt,'duration_ms':node.duration_ms},
            f'workflow-node:{node.id}:succeeded')
        instance.worker_lease_until = None
        instance.updated_at = now
        fdr = await session.get(FDR, instance.fdr_id)
        if node.node_key == 'route_case' or branch == 'correction':
            if branch == 'correction':
                lifecycle, execution = workflow_transition(instance, 'NEEDS_CORRECTION')
                fdr.status = FDRStatus.MISMATCH.value if node.node_key == 'route_case' else fdr.status
                fdr.lifecycle_state = LifecycleState.CORRECTION_REQUIRED.value
                fdr.execution_state = execution
                fdr.authorization_state = AuthorizationState.PENDING.value
                instance.lifecycle_state = lifecycle
                instance.execution_state = execution
                if not await session.scalar(select(CorrectionRequest.id).where(
                    CorrectionRequest.workflow_instance_id == instance.id,
                    CorrectionRequest.status == 'open')):
                    from app.models.user import User
                    institution_user = await session.scalar(select(User.id).where(
                        User.institution_id == instance.institution_id, User.role == 'institution').limit(1))
                    if institution_user:
                        correction=CorrectionRequest(workflow_instance_id=instance.id, fdr_id=fdr.id,
                            requested_by=institution_user,
                            reason='FDR scan could not be extracted or contains inconsistent required fields.',
                            required_fields=[{'discrepancy_id': item} for item in output.get('discrepancy_ids', [])],
                            due_at=now + timedelta(days=30))
                        session.add(correction); await session.flush()
                        institution=await session.get(Institution,instance.institution_id)
                        stage=f'CORRECTION-{correction.id}'
                        if institution and institution.contact_email and not await session.scalar(select(Notification.id).where(
                            Notification.fdr_id==fdr.id,Notification.stage==stage,Notification.channel=='email')):
                            import html
                            notification=Notification(fdr_id=fdr.id,stage=stage,channel='email',
                                recipient=institution.contact_email,status='queued')
                            session.add(notification);await session.flush()
                            safe_number=html.escape(fdr.fdr_number)
                            await enqueue_outbox(session,str(fdr.id),'DELIVER_NOTIFICATION',
                                {'notification_id':notification.id,'channel':'email','recipient':institution.contact_email,
                                 'subject':f'FDR correction required: {fdr.fdr_number}',
                                 'body':f'<p>Further information or a corrected scan is required for FDR {safe_number}. Sign in to your institution portal to review the case.</p>',
                                 'template_version':'correction-request-v1'},
                                f'correction:{correction.id}:notification:institution')
                instance.next_wake_at = now + timedelta(days=30)
                if not await session.scalar(select(ExceptionItem.id).where(
                    ExceptionItem.workflow_instance_id == instance.id,
                    ExceptionItem.reason_code.in_(['HIGH_DISCREPANCY','OCR_INPUT_REQUIRED']), ExceptionItem.status == 'open')):
                    session.add(ExceptionItem(workflow_instance_id=instance.id,
                        reason_code='HIGH_DISCREPANCY' if output.get('discrepancy_ids') else 'OCR_INPUT_REQUIRED',
                        priority=1, status='open', evidence_refs=[{'discrepancy_id': item} for item in output.get('discrepancy_ids', [])],
                        recommended_action='AICTE Official review or institution correction is required.'))
            else:
                lifecycle, execution = workflow_transition(instance, 'READY_FOR_REVIEW')
                instance.lifecycle_state = lifecycle
                instance.execution_state = execution
                instance.authorization_state = AuthorizationState.PENDING.value
                fdr.lifecycle_state = lifecycle
                fdr.execution_state = execution
                fdr.authorization_state = AuthorizationState.PENDING.value
                if not await session.scalar(select(ExceptionItem.id).where(
                    ExceptionItem.workflow_instance_id==instance.id,
                    ExceptionItem.reason_code=='OFFICIAL_REVIEW_REQUIRED',ExceptionItem.status=='open')):
                    latest_verification=await session.scalar(select(VerificationRun).where(
                        VerificationRun.fdr_id==fdr.id).order_by(VerificationRun.created_at.desc()).limit(1))
                    session.add(ExceptionItem(workflow_instance_id=instance.id,
                        reason_code='OFFICIAL_REVIEW_REQUIRED',priority=2,status='open',
                        evidence_refs=[{'verification_run_id':latest_verification.id} if latest_verification else
                            {'source':'declared_and_extracted_records'}],
                        recommended_action='Review the institution declaration, document extraction and any demo-gateway result; record an authorized decision.'))
            instance.current_node = None
            await publish(session, instance.id, 'WORKFLOW_ROUTED', output,
                f'workflow:{instance.id}:execution:{instance.execution_version}:routed:{node.id}')
            await record(session, None, 'workflow', instance.id, 'WORKFLOW_ROUTED', 'worker', output,
                actor_type='system', institution_id=instance.institution_id)
        else:
            _, instance.execution_state = workflow_transition(instance, 'NODE_SUCCEEDED')
            following = next_node(node.node_key, branch)
            instance.current_node = following
            instance.version += 1
            if following:
                await enqueue_outbox(session, str(instance.id), 'WORKFLOW_WAKE',
                    {'workflow_instance_id': instance.id, 'after_node_execution_id': node.id},
                    f'workflow:{instance.id}:execution:{instance.execution_version}:after-node:{node.id}')
            await publish(session,instance.id,'state.changed',{'lifecycle_state':instance.lifecycle_state,
                'execution_state':instance.execution_state,'current_node':instance.current_node},
                f'workflow:{instance.id}:state:{instance.version}:{instance.execution_state}:{instance.current_node or "waiting"}')
        await session.commit()


async def _fail_node(claim: dict, exc: Exception):
    now = _utcnow()
    async with SessionLocal() as session:
        instance = await session.scalar(select(WorkflowInstance).where(
            WorkflowInstance.id == claim['workflow_id']).with_for_update())
        node = await session.get(WorkflowNodeExecution, claim['run_id'])
        if not instance or not node: return
        node.status = 'failed'; node.finished_at = now
        node.duration_ms = max(0, int((now - _aware(node.started_at)).total_seconds() * 1000))
        node.error_class = 'INPUT' if isinstance(exc, InputFailure) else 'TRANSIENT' if isinstance(exc, TransientFailure) else 'PERMANENT'
        node.error_code = type(exc).__name__
        node.error_message = str(exc)[:2000]
        instance.worker_lease_until = None
        attempts = int((await session.scalar(select(func.count(WorkflowNodeExecution.id)).where(
            WorkflowNodeExecution.workflow_instance_id == instance.id,
            WorkflowNodeExecution.node_key == node.node_key))) or 1)
        if isinstance(exc, TransientFailure) and attempts < NODES[node.node_key].max_attempts:
            _, instance.execution_state = workflow_transition(instance, 'TRANSIENT_FAILURE')
            instance.next_wake_at = now + timedelta(seconds=min(NODES[node.node_key].retry_base_seconds * (2 ** (attempts - 1)), 300))
            await enqueue_outbox(session, str(instance.id), 'WORKFLOW_WAKE',
                {'workflow_instance_id': instance.id, 'retry_node': node.node_key},
                f'workflow:{instance.id}:node:{node.node_key}:retry:{attempts}')
        else:
            _, instance.execution_state = workflow_transition(instance, 'PERMANENT_FAILURE')
            instance.lifecycle_state = LifecycleState.VALIDATION_FAILED.value if isinstance(exc, InputFailure) else instance.lifecycle_state
            session.add(ExceptionItem(workflow_instance_id=instance.id, reason_code=node.error_code or 'NODE_FAILURE',
                priority=1, status='open', evidence_refs=[{'node_execution_id': node.id}],
                recommended_action='Inspect the failed workflow step and retry only after the input or dependency issue is addressed.'))
            await publish(session,instance.id,'exception.created',{'node_execution_id':node.id,
                'reason_code':node.error_code or 'NODE_FAILURE'},
                f'workflow:{instance.id}:exception:node:{node.id}')
        instance.version += 1
        await record(session, None, 'workflow_node_execution', node.id, 'NODE_FAILED', 'worker',
            {'status': ['running','failed'], 'error_class': [None,node.error_class], 'error_code': [None,node.error_code]},
            actor_type='system', institution_id=instance.institution_id)
        await publish(session,instance.id,'node.failed',{'node_execution_id':node.id,
            'node_key':node.node_key,'error_code':node.error_code,'error_class':node.error_class},
            f'workflow-node:{node.id}:failed')
        await session.commit()


async def _process_workflow(workflow_id: int):
    # Bound one task invocation to prevent a worker monopolizing a slot.
    for _ in range(3):
        claim = await _claim_next_node(workflow_id)
        if not claim: return
        try:
            output, branch = await asyncio.wait_for(_execute_node(claim), timeout=NODES[claim['node']].timeout_seconds)
            await _finish_node(claim, output, branch)
        except Exception as exc:
            logger.exception('workflow node failed workflow=%s node=%s', workflow_id, claim['node'])
            if isinstance(exc, asyncio.TimeoutError):
                exc = TransientFailure(f'Node timed out after {NODES[claim["node"]].timeout_seconds}s')
            await _fail_node(claim, exc)
            return
