"""USP 3 - Trust badge computation."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import TrustBadge, FDRStatus, VerificationLevel
from app.models.fdr import FDR
from app.models.discrepancy import Discrepancy
from app.schemas.verification import BankVerifyResponse, DiscrepancyOut
from app.services.audit_service import record
from app.services.workflow_state_service import sync_legacy_status, strongest_verification_level
from app.models.workflow import ExceptionItem
from sqlalchemy import select


async def compute_badge(bank: BankVerifyResponse | None, discrepancies: list[DiscrepancyOut]) -> TrustBadge:
    # BANK_VERIFIED if bank.found and no unresolved high discrepancy; MISMATCH if any high; else SELF_DECLARED
    if any(not getattr(d,'resolved',False) and d.severity=='high' for d in discrepancies): return TrustBadge.MISMATCH
    if bank and bank.found and bank.status=='ACTIVE': return TrustBadge.BANK_VERIFIED
    return TrustBadge.SELF_DECLARED


async def apply_badge(session: AsyncSession, fdr_id: int, *, persist_workflow_event: bool = True) -> FDR:
    # Recompute and persist badge + status (VERIFIED/MISMATCH)
    fdr=await session.get(FDR,fdr_id)
    if not fdr: raise ValueError('FDR not found')
    rows=(await session.scalars(select(Discrepancy).where(Discrepancy.fdr_id==fdr_id))).all()
    from app.schemas.verification import BankVerifyResponse
    bank=BankVerifyResponse(**fdr.bank_data) if fdr.bank_data else None
    badge=await compute_badge(bank,rows); old={'trust_badge':fdr.trust_badge,'status':fdr.status}
    fdr.trust_badge=badge.value
    candidate_level = (VerificationLevel.MOCK_VERIFIED.value if bank and bank.found
        else VerificationLevel.EXTRACTED.value if fdr.ocr_data else VerificationLevel.DECLARED.value)
    fdr.verification_level = strongest_verification_level(fdr.verification_level, candidate_level)
    if badge==TrustBadge.MISMATCH: fdr.status=FDRStatus.MISMATCH.value
    workflow = await sync_legacy_status(session, fdr, event_type='VERIFICATION_RESULT') if persist_workflow_event else None
    high_open = [row for row in rows if not row.resolved and row.severity == 'high']
    if persist_workflow_event and high_open and not await session.scalar(select(ExceptionItem.id).where(
        ExceptionItem.workflow_instance_id == workflow.id,
        ExceptionItem.reason_code == 'HIGH_DISCREPANCY', ExceptionItem.status == 'open')):
        session.add(ExceptionItem(workflow_instance_id=workflow.id, reason_code='HIGH_DISCREPANCY',
            priority=1, status='open', evidence_refs=[{'discrepancy_id': row.id,
                'field': row.field, 'source': row.source} for row in high_open],
            recommended_action='Official review or institution correction is required.'))
    await record(session,None,'fdr',fdr.id,'verification_result','system',{'trust_badge':[old['trust_badge'],fdr.trust_badge],'status':[old['status'],fdr.status]})
    return fdr
