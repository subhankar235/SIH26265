"""Append-only audit writer/reader."""

from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.audit_log import AuditLog
from app.core.deps import Pagination


async def record(session: AsyncSession, user_id: int | None, entity: str, entity_id: int, action: str, ip: str, delta: dict) -> None:
    # INSERT only. Never UPDATE/DELETE
    # The schema uses timezone-naive TIMESTAMP columns; store a naive UTC value consistently.
    session.add(AuditLog(user_id=user_id,entity=entity,entity_id=entity_id,action=action,ip_address=ip or 'system',delta_changes=delta or {},created_at=datetime.now(timezone.utc).replace(tzinfo=None)))


async def query_logs(session: AsyncSession, filters: dict, page: Pagination) -> list[AuditLog]:
    # Filter by entity/user/date
    query=select(AuditLog).order_by(AuditLog.created_at.desc())
    for field in ('entity','entity_id','user_id'):
        if filters.get(field) is not None: query=query.where(getattr(AuditLog,field)==filters[field])
    query=query.offset(page.skip).limit(page.limit)
    return list((await session.scalars(query)).all())
