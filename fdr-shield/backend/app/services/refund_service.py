"""Discharge workflow."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from sqlalchemy import select
from app.models.fdr import FDR
from app.models.refund_request import RefundRequest
from app.core.enums import FDRStatus
from app.core.exceptions import NotFound, InvalidStateTransition
from app.services.audit_service import record
from app.schemas.refund import RefundCreate
from app.core.deps import Pagination


async def create_refund(session: AsyncSession, data: RefundCreate, user_id: int, institution_id: int | None = None) -> RefundRequest:
    # Eligibility check then insert
    f=await session.get(FDR,data.fdr_id)
    if not f or (institution_id is not None and f.institution_id != institution_id) or f.status!=FDRStatus.VERIFIED.value or f.maturity_date>date.today():raise InvalidStateTransition('Refund requires a verified, matured FDR')
    r=RefundRequest(fdr_id=f.id,requested_by=user_id,status='pending',remarks=data.reason);session.add(r);await session.flush()
    await record(session,user_id,'refund',r.id,'created','',{'status':[None,r.status]});return r


async def decide(session: AsyncSession, refund_id: int, decision: str, remarks: str, user_id: int) -> RefundRequest:
    # approve -> FDR RELEASED; audit
    r=await session.get(RefundRequest,refund_id)
    if not r or r.status!='pending':raise NotFound('Pending refund not found')
    if decision not in {'approved','rejected'}:raise ValueError('Decision must be approved or rejected')
    f=await session.get(FDR,r.fdr_id);old=r.status;r.status=decision;r.reviewed_by=user_id;r.remarks=remarks
    if decision=='approved':f.status=FDRStatus.RELEASED.value
    await record(session,user_id,'refund',r.id,'decision','',{'status':[old,decision],'remarks':[None,remarks]})
    if decision=='approved':await record(session,user_id,'fdr',f.id,'released','',{'status':[FDRStatus.VERIFIED.value,FDRStatus.RELEASED.value]})
    return r


async def list_refunds(session: AsyncSession, status: str | None, institution_id: int | None, page: Pagination) -> list[RefundRequest]:
    query=select(RefundRequest).join(FDR)
    if institution_id is not None: query=query.where(FDR.institution_id==institution_id)
    if status: query=query.where(RefundRequest.status==status)
    query=query.order_by(RefundRequest.id.desc()).offset(page.skip).limit(page.limit)
    return list((await session.scalars(query)).all())
