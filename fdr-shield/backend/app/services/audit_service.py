"""Append-only audit writer/reader."""

from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
import hashlib
import json
from sqlalchemy import select
from app.models.audit_log import AuditChainHead, AuditLog
from app.core.deps import Pagination
from sqlalchemy import select


async def _resolve_institution_id(session: AsyncSession, entity: str, entity_id: int) -> int | None:
    from app.models.user import User
    from app.models.fdr import FDR
    from app.models.document import Document
    from app.models.refund_request import RefundRequest
    from app.models.discrepancy import Discrepancy
    if entity == 'institution':
        return entity_id
    if entity == 'user':
        return await session.scalar(select(User.institution_id).where(User.id == entity_id))
    if entity == 'fdr':
        return await session.scalar(select(FDR.institution_id).where(FDR.id == entity_id))
    if entity == 'document':
        return await session.scalar(select(FDR.institution_id).join(Document, Document.fdr_id == FDR.id)
            .where(Document.id == entity_id))
    if entity == 'refund':
        return await session.scalar(select(FDR.institution_id).join(RefundRequest, RefundRequest.fdr_id == FDR.id)
            .where(RefundRequest.id == entity_id))
    if entity == 'discrepancy':
        return await session.scalar(select(FDR.institution_id).join(Discrepancy, Discrepancy.fdr_id == FDR.id)
            .where(Discrepancy.id == entity_id))
    return None


async def record(session: AsyncSession, user_id: int | None, entity: str, entity_id: int, action: str,
                 ip: str, delta: dict, *, actor_type: str | None = None,
                 institution_id: int | None = None, request_id: str | None = None) -> None:
    # INSERT only. Never UPDATE/DELETE
    # The schema uses timezone-naive TIMESTAMP columns; store a naive UTC value consistently.
    from app.core.request_context import request_id_context
    request_id = request_id or request_id_context.get()
    if institution_id is None:
        institution_id = await _resolve_institution_id(session, entity, entity_id)
    head = await session.scalar(select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update())
    if head is None:
        head = AuditChainHead(id=1, latest_log_id=None, chain_hash='0' * 64)
        session.add(head)
        await session.flush()
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    values = {'user_id': user_id, 'actor_type': actor_type or ('system' if user_id is None else 'user'),
        'institution_id': institution_id, 'request_id': request_id, 'entity': entity,
        'entity_id': entity_id, 'action': action, 'ip_address': (ip or 'system')[:255],
        'delta_changes': delta or {}, 'created_at': created_at}
    payload = {**values, 'created_at': created_at.isoformat()}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
    previous_hash = head.chain_hash
    record_hash = hashlib.sha256((previous_hash + canonical).encode('utf-8')).hexdigest()
    log = AuditLog(**values, previous_hash=previous_hash, record_hash=record_hash)
    session.add(log)
    await session.flush()
    head.latest_log_id = log.id
    head.chain_hash = record_hash


async def verify_audit_chain(session: AsyncSession) -> dict:
    """Recompute all hashes and compare both links and the serialized chain head."""
    head = await session.scalar(select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update())
    rows = list((await session.scalars(select(AuditLog).order_by(AuditLog.id))).all())
    previous = '0' * 64
    errors = []
    for row in rows:
        payload = {'user_id': row.user_id, 'actor_type': row.actor_type,
            'institution_id': row.institution_id, 'request_id': row.request_id,
            'entity': row.entity, 'entity_id': row.entity_id, 'action': row.action,
            'ip_address': row.ip_address, 'delta_changes': row.delta_changes,
            'created_at': row.created_at.isoformat()}
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
        expected = hashlib.sha256((previous + canonical).encode('utf-8')).hexdigest()
        if row.previous_hash != previous or row.record_hash != expected:
            errors.append({'audit_id': row.id, 'problem': 'hash_or_link_mismatch'})
        previous = row.record_hash
    if (head.chain_hash if head else '0' * 64) != previous:
        errors.append({'audit_id': head.latest_log_id if head else None, 'problem': 'chain_head_mismatch'})
    if head and head.latest_log_id != (rows[-1].id if rows else None):
        errors.append({'audit_id': head.latest_log_id, 'problem': 'chain_head_position_mismatch'})
    return {'valid': not errors, 'record_count': len(rows), 'head_hash': previous, 'errors': errors}


async def export_audit_chain(session: AsyncSession) -> dict:
    """Return append-only export material and its verifiable chain watermark."""
    verification = await verify_audit_chain(session)
    rows = list((await session.scalars(select(AuditLog).order_by(AuditLog.id))).all())
    records = [{'id': row.id, 'previous_hash': row.previous_hash, 'record_hash': row.record_hash,
        'created_at': row.created_at.isoformat(), 'user_id': row.user_id, 'actor_type': row.actor_type,
        'institution_id': row.institution_id, 'request_id': row.request_id, 'entity': row.entity,
        'entity_id': row.entity_id, 'action': row.action, 'ip_address': row.ip_address,
        'delta_changes': row.delta_changes} for row in rows]
    return {'exported_at': datetime.now(timezone.utc).isoformat(), 'verification': verification, 'records': records}


async def query_logs(session: AsyncSession, filters: dict, page: Pagination) -> list[AuditLog]:
    # Filter by entity/user/date
    query=select(AuditLog).order_by(AuditLog.created_at.desc())
    for field in ('entity','entity_id','user_id'):
        if filters.get(field) is not None: query=query.where(getattr(AuditLog,field)==filters[field])
    query=query.offset(page.skip).limit(page.limit)
    return list((await session.scalars(query)).all())
