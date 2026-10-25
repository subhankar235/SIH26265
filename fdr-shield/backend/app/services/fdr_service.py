"""FDR lifecycle & state machine."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from sqlalchemy import select
from app.models.fdr import FDR
from app.models.discrepancy import Discrepancy
from app.models.workflow import CorrectionRequest
from app.core.enums import FDRStatus, TrustBadge
from app.core.exceptions import NotFound, InvalidStateTransition
from app.services.audit_service import record
from app.schemas.fdr import FDRCreate, RenewalRequest
from app.core.enums import LifecycleState, VerificationLevel
from app.services.workflow_state_service import sync_legacy_status, record_human_decision

ALLOWED_TRANSITIONS={FDRStatus.SUBMITTED.value:{FDRStatus.UNDER_SCRUTINY.value,FDRStatus.VERIFIED.value,FDRStatus.MISMATCH.value},FDRStatus.UNDER_SCRUTINY.value:{FDRStatus.VERIFIED.value,FDRStatus.MISMATCH.value},FDRStatus.MISMATCH.value:{FDRStatus.UNDER_SCRUTINY.value,FDRStatus.VERIFIED.value},FDRStatus.VERIFIED.value:{FDRStatus.RELEASE_REQUESTED.value,FDRStatus.RENEWAL_REQUESTED.value,FDRStatus.EXPIRED.value},FDRStatus.RELEASE_REQUESTED.value:{FDRStatus.RELEASED.value,FDRStatus.VERIFIED.value}}


async def get_fdr(session: AsyncSession, fdr_id: int, institution_id: int | None = None) -> FDR:
    fdr = await session.get(FDR, fdr_id)
    if not fdr or (institution_id is not None and fdr.institution_id != institution_id):
        raise NotFound('FDR not found')
    return fdr


async def create_fdr(session: AsyncSession, data: FDRCreate, institution_id: int, user_id: int) -> FDR:
    # Insert FDR(status=SUBMITTED, trust_badge=SELF_DECLARED, declared_data=data.dict())
    f=FDR(institution_id=institution_id,fdr_number=data.fdr_number,bank_name=data.bank_name,branch=data.branch,amount=data.amount,issue_date=data.issue_date,maturity_date=data.maturity_date,status=FDRStatus.SUBMITTED.value,lifecycle_state=LifecycleState.SUBMITTED.value,verification_level=VerificationLevel.DECLARED.value,trust_badge=TrustBadge.SELF_DECLARED.value,declared_data=data.model_dump(mode='json'))
    session.add(f); await session.flush()
    await sync_legacy_status(session, f, actor_id=user_id, event_type='FDR_SUBMITTED', previous_status=None)
    await record(session,user_id,'fdr',f.id,'created','',{'status':[None,f.status]})
    return f


async def transition(session: AsyncSession, fdr_id: int, new_status: FDRStatus, user_id: int,
                     remarks: str | None, *, approval_idempotency_key: str | None = None,
                     decision_override: str | None = None) -> FDR:
    # Check ALLOWED_TRANSITIONS map; raise InvalidStateTransition; audit
    f=await session.get(FDR,fdr_id)
    if not f: raise NotFound('FDR not found')
    target=getattr(new_status,'value',new_status)
    if target not in ALLOWED_TRANSITIONS.get(f.status,set()): raise InvalidStateTransition(f'{f.status} cannot transition to {target}')
    if target in {FDRStatus.VERIFIED.value, FDRStatus.MISMATCH.value} and not (remarks and remarks.strip()):
        raise InvalidStateTransition('An official scrutiny rationale is required for approval or correction request.')
    old=f.status; f.status=target
    if target in {FDRStatus.VERIFIED.value, FDRStatus.MISMATCH.value}:
        f.verification_level = VerificationLevel.HUMAN_SCRUTINIZED.value
    instance = await sync_legacy_status(session, f, actor_id=user_id,
        event_type='OFFICIAL_FDR_DECISION' if target in {FDRStatus.VERIFIED.value, FDRStatus.MISMATCH.value} else 'OFFICIAL_REVIEW_STARTED' if target == FDRStatus.UNDER_SCRUTINY.value else 'FDR_STATUS_CHANGED',
        previous_status=old)
    if target == FDRStatus.VERIFIED.value:
        instance.authorization_state = 'approved'
        await record_human_decision(session, f, user_id, 'aicte_official', decision_override or 'approve', remarks.strip(), idempotency_key=approval_idempotency_key)
    elif target == FDRStatus.MISMATCH.value:
        instance.authorization_state = 'pending'
        await record_human_decision(session, f, user_id, 'aicte_official', decision_override or 'request_correction', remarks.strip(), idempotency_key=approval_idempotency_key)
        discrepancies = list((await session.scalars(select(Discrepancy).where(
            Discrepancy.fdr_id == f.id, Discrepancy.resolved.is_(False)))).all())
        session.add(CorrectionRequest(workflow_instance_id=instance.id, fdr_id=f.id,
            requested_by=user_id, reason=remarks.strip(),
            required_fields=[{'field': row.field, 'source': row.source, 'severity': row.severity}
                for row in discrepancies]))
    await record(session,user_id,'fdr',f.id,'status_changed','',{'status':[old,target],'remarks':[None,remarks]})
    return f


async def list_fdrs(session: AsyncSession, filters: dict, scope_institution_id: int | None, page: Pagination) -> list[FDR]:
    # Dynamic filters for Trust Matrix
    q=select(FDR).order_by(FDR.maturity_date)
    for key in ('status','trust_badge'):
        if filters.get(key): q=q.where(getattr(FDR,key)==filters[key])
    inst=scope_institution_id or filters.get('institution_id')
    if inst: q=q.where(FDR.institution_id==inst)
    return list((await session.scalars(q.offset(page.skip).limit(page.limit))).all())


async def request_renewal(session: AsyncSession, fdr_id: int, data: RenewalRequest, user_id: int, institution_id: int | None = None) -> FDR:
    # Create replacement FDR linked to old; old -> RENEWAL_REQUESTED
    old=await get_fdr(session,fdr_id,institution_id)
    new=FDR(institution_id=old.institution_id,fdr_number=data.new_fdr_number,bank_name=old.bank_name,branch=old.branch,amount=data.amount,issue_date=date.today(),maturity_date=data.new_maturity_date,status=FDRStatus.SUBMITTED.value,lifecycle_state=LifecycleState.SUBMITTED.value,verification_level=VerificationLevel.DECLARED.value,trust_badge=TrustBadge.SELF_DECLARED.value,declared_data={**old.declared_data,'fdr_number':data.new_fdr_number,'amount':float(data.amount),'maturity_date':data.new_maturity_date.isoformat()},replaces_fdr_id=old.id)
    session.add(new); await session.flush()
    previous=old.status; old.status=FDRStatus.RENEWAL_REQUESTED.value
    await sync_legacy_status(session, old, actor_id=user_id, event_type='FDR_RENEWAL_REQUESTED', previous_status=previous)
    await sync_legacy_status(session, new, actor_id=user_id, event_type='REPLACEMENT_FDR_SUBMITTED', previous_status=None)
    await record(session,user_id,'fdr',old.id,'renewal_requested','',{'status':[previous,old.status],'replacement_id':[None,new.id]})
    await record(session,user_id,'fdr',new.id,'created_as_renewal','',{'replaces_fdr_id':[None,old.id]})
    return new


async def days_to_maturity(fdr: FDR) -> int:
    # (maturity_date - today).days
    return (fdr.maturity_date-date.today()).days
