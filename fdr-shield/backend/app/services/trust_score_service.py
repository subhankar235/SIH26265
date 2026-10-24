"""USP 3 - Trust badge computation."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import TrustBadge, FDRStatus
from app.models.fdr import FDR
from app.models.discrepancy import Discrepancy
from app.schemas.verification import BankVerifyResponse, DiscrepancyOut
from app.services.audit_service import record
from sqlalchemy import select


async def compute_badge(bank: BankVerifyResponse | None, discrepancies: list[DiscrepancyOut]) -> TrustBadge:
    # BANK_VERIFIED if bank.found and no unresolved high discrepancy; MISMATCH if any high; else SELF_DECLARED
    if any(not getattr(d,'resolved',False) and d.severity=='high' for d in discrepancies): return TrustBadge.MISMATCH
    if bank and bank.found and bank.status=='ACTIVE': return TrustBadge.BANK_VERIFIED
    return TrustBadge.SELF_DECLARED


async def apply_badge(session: AsyncSession, fdr_id: int) -> FDR:
    # Recompute and persist badge + status (VERIFIED/MISMATCH)
    fdr=await session.get(FDR,fdr_id)
    if not fdr: raise ValueError('FDR not found')
    rows=(await session.scalars(select(Discrepancy).where(Discrepancy.fdr_id==fdr_id))).all()
    from app.schemas.verification import BankVerifyResponse
    bank=BankVerifyResponse(**fdr.bank_data) if fdr.bank_data else None
    badge=await compute_badge(bank,rows); old={'trust_badge':fdr.trust_badge,'status':fdr.status}
    fdr.trust_badge=badge.value
    if badge==TrustBadge.MISMATCH: fdr.status=FDRStatus.MISMATCH.value
    await record(session,None,'fdr',fdr.id,'verification_result','system',{'trust_badge':[old['trust_badge'],fdr.trust_badge],'status':[old['status'],fdr.status]})
    return fdr
