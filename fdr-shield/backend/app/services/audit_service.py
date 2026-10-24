"""Append-only audit writer/reader."""

from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.audit_log import AuditLog
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
    if institution_id is None:
        institution_id = await _resolve_institution_id(session, entity, entity_id)
    session.add(AuditLog(user_id=user_id,entity=entity,entity_id=entity_id,action=action,
        ip_address=ip or 'system',delta_changes=delta or {},
        actor_type=actor_type or ('system' if user_id is None else 'user'),
        institution_id=institution_id,request_id=request_id,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None)))


async def query_logs(session: AsyncSession, filters: dict, page: Pagination) -> list[AuditLog]:
    # Filter by entity/user/date
    query=select(AuditLog).order_by(AuditLog.created_at.desc())
    for field in ('entity','entity_id','user_id'):
        if filters.get(field) is not None: query=query.where(getattr(AuditLog,field)==filters[field])
    query=query.offset(page.skip).limit(page.limit)
    return list((await session.scalars(query)).all())
