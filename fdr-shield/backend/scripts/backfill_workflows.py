"""Idempotently project legacy FDR status into the new workflow model.

Run after `alembic upgrade head`. Each chunk commits independently; rerunning is safe.
This imports current state only and does not invent historical workflow executions.
"""
import asyncio
from datetime import timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.enums import ExecutionState
from app.models.document import Document
from app.models.discrepancy import Discrepancy
from app.models.fdr import FDR
from app.models.audit_log import AuditLog
from app.models.refund_request import RefundRequest
from app.models.user import User
from app.models.workflow import ApprovalRecord, VerificationRun, WorkflowEvent, WorkflowInstance
from app.services.workflow_state_service import (LEGACY_STATUS_TO_LIFECYCLE,
    authorization_for_legacy_status, source_verification_level_for_fdr)

BATCH_SIZE = 250


async def backfill():
    last_id = 0
    processed = 0
    async with SessionLocal() as session:
        while True:
            rows = list((await session.scalars(select(FDR).where(FDR.id > last_id)
                .order_by(FDR.id).limit(BATCH_SIZE))).all())
            if not rows:
                break
            for fdr in rows:
                instance = await session.scalar(select(WorkflowInstance)
                    .where(WorkflowInstance.fdr_id == fdr.id,
                           WorkflowInstance.execution_version == 1))
                if instance is None:
                    lifecycle = fdr.lifecycle_state or LEGACY_STATUS_TO_LIFECYCLE.get(fdr.status, 'submitted')
                    fdr.lifecycle_state = lifecycle
                    fdr.verification_level = source_verification_level_for_fdr(fdr)
                    fdr.execution_state = fdr.execution_state or ExecutionState.NOT_STARTED.value
                    fdr.authorization_state = fdr.authorization_state or authorization_for_legacy_status(fdr.status)
                    instance = WorkflowInstance(fdr_id=fdr.id, institution_id=fdr.institution_id,
                        workflow_version='legacy-import-v1', execution_version=1,
                        lifecycle_state=lifecycle, execution_state=ExecutionState.NOT_STARTED.value,
                        authorization_state=fdr.authorization_state,
                        current_node='legacy_import')
                    session.add(instance)
                    await session.flush()
                    session.add(WorkflowEvent(workflow_instance_id=instance.id,
                        event_type='LEGACY_STATE_IMPORTED',
                        dedupe_key=f'legacy-backfill:fdr:{fdr.id}:v1',
                        payload={'fdr_id': fdr.id, 'legacy_status': fdr.status,
                                 'lifecycle_state': lifecycle,
                                  'execution_state': ExecutionState.NOT_STARTED.value,
                                  'note': 'Historical node runs were not available during import.'}))
                elif instance.workflow_version == 'legacy-import-v1':
                    lifecycle = fdr.lifecycle_state or LEGACY_STATUS_TO_LIFECYCLE.get(fdr.status, 'submitted')
                    fdr.lifecycle_state = lifecycle
                    fdr.verification_level = source_verification_level_for_fdr(fdr)
                    instance.lifecycle_state = lifecycle
                    instance.authorization_state = fdr.authorization_state or authorization_for_legacy_status(fdr.status)
                    fdr.execution_state = instance.execution_state
                    fdr.authorization_state = instance.authorization_state
                docs = list((await session.scalars(select(Document).where(Document.fdr_id == fdr.id)
                    .order_by(Document.doc_type, Document.id))).all())
                previous_by_type = {}
                version_by_type = {}
                for document in docs:
                    next_version = version_by_type.get(document.doc_type, 0) + 1
                    version_by_type[document.doc_type] = next_version
                    document.version_no = next_version
                    if document.doc_type in previous_by_type:
                        document.supersedes_document_id = previous_by_type[document.doc_type]
                    previous_by_type[document.doc_type] = document.id
                legacy_run_key = f'legacy-import:fdr:{fdr.id}:verification-v1'
                if (fdr.ocr_data is not None or fdr.bank_data is not None) and not await session.scalar(
                    select(VerificationRun.id).where(VerificationRun.idempotency_key == legacy_run_key)):
                    scan = next((document for document in reversed(docs) if document.doc_type == 'fdr_scan'), None)
                    discrepancy_rows = list((await session.scalars(select(Discrepancy)
                        .where(Discrepancy.fdr_id == fdr.id).order_by(Discrepancy.id))).all())
                    session.add(VerificationRun(fdr_id=fdr.id, document_id=scan.id if scan else None,
                        extraction_engine='legacy_snapshot', engine_version=None, source='legacy_import',
                        verification_level=source_verification_level_for_fdr(fdr), idempotency_key=legacy_run_key,
                        declared_snapshot=fdr.declared_data or {}, extracted_fields=fdr.ocr_data,
                        bank_result=fdr.bank_data,
                        discrepancies=[{'field': row.field, 'declared_value': row.declared_value,
                            'extracted_value': row.extracted_value, 'source': row.source,
                            'severity': row.severity, 'resolved': row.resolved} for row in discrepancy_rows],
                        confidence=(fdr.ocr_data or {}).get('confidence')))
                discrepancy_rows = list((await session.scalars(select(Discrepancy)
                    .where(Discrepancy.fdr_id == fdr.id).order_by(Discrepancy.id))).all())
                unresolved_high = [row for row in discrepancy_rows if not row.resolved and row.severity == 'high']
                if unresolved_high and not await session.scalar(select(WorkflowEvent.id).where(
                    WorkflowEvent.workflow_instance_id == instance.id,
                    WorkflowEvent.event_type == 'LEGACY_EXCEPTION_IMPORTED')):
                    from app.models.workflow import ExceptionItem
                    session.add(ExceptionItem(workflow_instance_id=instance.id, reason_code='HIGH_DISCREPANCY',
                        priority=1, status='open', evidence_refs=[{'discrepancy_id': row.id,
                            'field': row.field, 'source': row.source} for row in unresolved_high],
                        recommended_action='Official review or institution correction is required.'))
                    session.add(WorkflowEvent(workflow_instance_id=instance.id,
                        event_type='LEGACY_EXCEPTION_IMPORTED',
                        dedupe_key=f'legacy-backfill:fdr:{fdr.id}:exception-v1',
                        payload={'fdr_id': fdr.id, 'open_high_discrepancies': [row.id for row in unresolved_high]}))

                status_audits = list((await session.scalars(select(AuditLog).where(
                    AuditLog.entity == 'fdr', AuditLog.entity_id == fdr.id,
                    AuditLog.action == 'status_changed').order_by(AuditLog.id))).all())
                for audit in status_audits:
                    changes = audit.delta_changes or {}
                    status_delta = changes.get('status') or []
                    remarks_delta = changes.get('remarks') or []
                    if len(status_delta) < 2 or len(remarks_delta) < 2 or not remarks_delta[1] or not audit.user_id:
                        continue
                    target = status_delta[1]
                    decision = 'approve' if target == 'verified' else 'request_correction' if target == 'mismatch' else None
                    actor = await session.get(User, audit.user_id)
                    existing_approval = await session.scalar(select(ApprovalRecord.id).where(
                        ApprovalRecord.source_audit_id == audit.id))
                    if not decision or not actor or existing_approval:
                        continue
                    fdr.verification_level = 'human_scrutinized'
                    created_at = audit.created_at.replace(tzinfo=timezone.utc) if audit.created_at.tzinfo is None else audit.created_at
                    session.add(ApprovalRecord(workflow_instance_id=instance.id, fdr_id=fdr.id,
                        request_type='fdr_scrutiny', decision=decision, rationale=str(remarks_delta[1]),
                        actor_user_id=actor.id, actor_role=actor.role, source_audit_id=audit.id,
                        created_at=created_at))

                refund_rows = list((await session.scalars(select(RefundRequest).where(RefundRequest.fdr_id == fdr.id))).all())
                for refund in refund_rows:
                    if refund.status not in {'approved','rejected'} or not refund.reviewed_by:
                        continue
                    decision_audit = await session.scalar(select(AuditLog).where(
                        AuditLog.entity == 'refund', AuditLog.entity_id == refund.id,
                        AuditLog.action == 'decision').order_by(AuditLog.id.desc()).limit(1))
                    actor = await session.get(User, refund.reviewed_by)
                    if not decision_audit or not actor or await session.scalar(select(ApprovalRecord.id).where(
                        ApprovalRecord.source_audit_id == decision_audit.id)):
                        continue
                    rationale = refund.remarks or (decision_audit.delta_changes or {}).get('remarks', [None, None])[1]
                    if not rationale:
                        continue
                    created_at = decision_audit.created_at.replace(tzinfo=timezone.utc) if decision_audit.created_at.tzinfo is None else decision_audit.created_at
                    session.add(ApprovalRecord(workflow_instance_id=instance.id, fdr_id=fdr.id,
                        refund_request_id=refund.id, request_type='release_refund',
                        decision='approve' if refund.status == 'approved' else 'reject',
                        rationale=str(rationale), actor_user_id=actor.id, actor_role=actor.role,
                        source_audit_id=decision_audit.id, created_at=created_at))
            last_id = rows[-1].id
            processed += len(rows)
            await session.commit()
    print(f'Backfilled workflow projections for {processed} FDR records through id={last_id}.')


if __name__ == '__main__':
    asyncio.run(backfill())
