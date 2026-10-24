"""Read and review operations for verification reports and discrepancies."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Pagination
from app.core.exceptions import NotFound
from app.models.discrepancy import Discrepancy
from app.models.fdr import FDR
from app.services.audit_service import record


async def get_report(session: AsyncSession, fdr_id: int, institution_id: int | None = None) -> dict:
    fdr = await session.get(FDR, fdr_id)
    if not fdr or (institution_id is not None and fdr.institution_id != institution_id):
        raise NotFound('FDR not found')
    rows = (await session.scalars(select(Discrepancy).where(Discrepancy.fdr_id == fdr_id).order_by(Discrepancy.id))).all()
    return {'ocr': fdr.ocr_data, 'bank': fdr.bank_data, 'discrepancies': rows, 'trust_badge': fdr.trust_badge}


async def resolve_discrepancy(session: AsyncSession, discrepancy_id: int, remarks: str, user_id: int, actor: str) -> Discrepancy:
    discrepancy = await session.get(Discrepancy, discrepancy_id)
    if not discrepancy: raise NotFound('Discrepancy not found')
    if not discrepancy.resolved:
        discrepancy.resolved = True
        await record(session, user_id, 'discrepancy', discrepancy.id, 'resolved', actor,
                     {'resolved': [False, True], 'remarks': [None, remarks]})
    return discrepancy


async def list_discrepancies(session: AsyncSession, resolved: bool, page: Pagination) -> list[Discrepancy]:
    query = select(Discrepancy).where(Discrepancy.resolved == resolved).order_by(Discrepancy.id.desc())
    return list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
