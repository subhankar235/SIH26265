"""Read and review operations for verification reports and discrepancies."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Pagination
from app.core.exceptions import NotFound
from app.models.discrepancy import Discrepancy
from app.models.fdr import FDR
<<<<<<< HEAD
from app.models.institution import Institution
=======
>>>>>>> a27ee110f6ba3d79cb2eb0cff239996b7f97ea26
from app.models.workflow import WorkflowInstance, WorkflowNodeExecution
from app.services.audit_service import record
from app.core.config import get_settings


async def get_report(session: AsyncSession, fdr_id: int, institution_id: int | None = None,
                     include_review_assessment: bool = False) -> dict:
    fdr = await session.get(FDR, fdr_id)
    if not fdr or (institution_id is not None and fdr.institution_id != institution_id):
        raise NotFound('FDR not found')
    rows = (await session.scalars(select(Discrepancy).where(Discrepancy.fdr_id == fdr_id).order_by(Discrepancy.id))).all()
    workflow = await session.scalar(select(WorkflowInstance).where(
        WorkflowInstance.fdr_id == fdr_id
    ).order_by(WorkflowInstance.execution_version.desc()).limit(1))
    processing = None
<<<<<<< HEAD
    review_assessment = None
=======
>>>>>>> a27ee110f6ba3d79cb2eb0cff239996b7f97ea26
    if workflow:
        latest_node = await session.scalar(select(WorkflowNodeExecution).where(
            WorkflowNodeExecution.workflow_instance_id == workflow.id
        ).order_by(WorkflowNodeExecution.id.desc()).limit(1))
        extraction_node = await session.scalar(select(WorkflowNodeExecution).where(
            WorkflowNodeExecution.workflow_instance_id == workflow.id,
            WorkflowNodeExecution.node_key == 'extract_document',
        ).order_by(WorkflowNodeExecution.id.desc()).limit(1))
        processing = {
            'execution_state': workflow.execution_state,
            'current_node': workflow.current_node,
            'last_node': latest_node.node_key if latest_node else None,
            'last_node_status': latest_node.status if latest_node else None,
            'last_error_code': latest_node.error_code if latest_node and latest_node.status == 'failed' else None,
            'extraction_status': extraction_node.status if extraction_node else None,
            'extraction_error_code': extraction_node.error_code
                if extraction_node and extraction_node.status == 'failed' else None,
            'extraction_confidence': (extraction_node.output_ref or {}).get('confidence')
                if extraction_node and extraction_node.status == 'succeeded' else None,
            'extraction_completed_at': extraction_node.finished_at.isoformat()
                if extraction_node and extraction_node.finished_at else None,
        }
        if get_settings().celery_task_always_eager:
            processing['local_inline_enabled'] = True
<<<<<<< HEAD
        if include_review_assessment:
            validation_node = await session.scalar(select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_instance_id == workflow.id,
                WorkflowNodeExecution.node_key == 'validate_fields',
                WorkflowNodeExecution.status == 'succeeded').order_by(WorkflowNodeExecution.id.desc()).limit(1))
            raw_assessment = (validation_node.output_ref or {}).get('review_assessment') if validation_node else None
            if isinstance(raw_assessment, dict) and raw_assessment.get('assessment') not in (None, 'unavailable'):
                # The official review surface receives only the advisory category
                # and deterministic safe summary, never provider/model identifiers.
                review_assessment = {'assessment': raw_assessment.get('assessment'),
                    'summary': raw_assessment.get('summary')}
    return {'ocr': fdr.ocr_data, 'bank': fdr.bank_data, 'discrepancies': rows,
            'trust_badge': fdr.trust_badge, 'processing': processing,
            'review_assessment': review_assessment}
=======
    return {'ocr': fdr.ocr_data, 'bank': fdr.bank_data, 'discrepancies': rows,
            'trust_badge': fdr.trust_badge, 'processing': processing}
>>>>>>> a27ee110f6ba3d79cb2eb0cff239996b7f97ea26


async def resolve_discrepancy(session: AsyncSession, discrepancy_id: int, remarks: str, user_id: int, actor: str) -> Discrepancy:
    discrepancy = await session.get(Discrepancy, discrepancy_id)
    if not discrepancy: raise NotFound('Discrepancy not found')
    if not discrepancy.resolved:
        discrepancy.resolved = True
        await record(session, user_id, 'discrepancy', discrepancy.id, 'resolved', actor,
                     {'resolved': [False, True], 'remarks': [None, remarks]})
    return discrepancy


async def list_discrepancies(session: AsyncSession, resolved: bool, page: Pagination,
                             real_only: bool = False) -> list[Discrepancy] | list[dict]:
    query = select(Discrepancy).where(Discrepancy.resolved == resolved).order_by(Discrepancy.id.desc())
    if real_only:
        rows = (await session.execute(select(Discrepancy, FDR, Institution.name)
            .join(FDR, FDR.id == Discrepancy.fdr_id)
            .join(Institution, Institution.id == FDR.institution_id)
            .where(Discrepancy.resolved == resolved, FDR.is_synthetic.is_(False))
            .order_by(Discrepancy.id.desc()).offset(page.skip).limit(page.limit + 1))).all()
        has_more = len(rows) > page.limit
        items = [{'id': discrepancy.id, 'fdr_id': fdr.id, 'fdr_number': fdr.fdr_number,
            'institution_name': institution_name, 'field': discrepancy.field,
            'declared_value': discrepancy.declared_value, 'extracted_value': discrepancy.extracted_value,
            'source': discrepancy.source, 'severity': discrepancy.severity,
            'resolved': discrepancy.resolved, 'detected_at': discrepancy.detected_at,
            'lifecycle_state': fdr.lifecycle_state or fdr.status}
            for discrepancy, fdr, institution_name in rows[:page.limit]]
        return {'items': items, 'has_more': has_more}
    return list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
