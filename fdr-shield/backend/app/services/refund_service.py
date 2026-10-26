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
from app.services.workflow_state_service import sync_legacy_status, record_human_decision
from app.models.workflow import ApprovalRecord
import html
from app.models.institution import Institution
from app.models.notification import Notification
from app.services.outbox_service import enqueue as enqueue_outbox
from app.core.clock import business_today


async def create_refund(session: AsyncSession, data: RefundCreate, user_id: int, institution_id: int | None = None) -> RefundRequest:
    # Eligibility check then insert
    f=await session.scalar(select(FDR).where(FDR.id==data.fdr_id).with_for_update())
    if not f or (institution_id is not None and f.institution_id != institution_id) or f.status!=FDRStatus.VERIFIED.value or f.maturity_date>business_today():raise InvalidStateTransition('Refund requires a verified, matured FDR')
    r=RefundRequest(fdr_id=f.id,requested_by=user_id,status='pending',remarks=data.reason);session.add(r);await session.flush()
    previous_status=f.status;f.status=FDRStatus.RELEASE_REQUESTED.value
    workflow=await sync_legacy_status(session,f,actor_id=user_id,event_type='RELEASE_REQUESTED',previous_status=previous_status)
    workflow.authorization_state='pending';f.authorization_state='pending'
    await record(session,user_id,'refund',r.id,'created','',{'status':[None,r.status]})
    await record(session,user_id,'fdr',f.id,'release_requested','',{'status':[previous_status,f.status]})
    return r


async def decide(session: AsyncSession, refund_id: int, decision: str, remarks: str, user_id: int,
                 idempotency_key: str | None = None) -> RefundRequest:
    # approve -> FDR RELEASED; audit
    r=await session.get(RefundRequest,refund_id)
    if idempotency_key:
        prior=await session.scalar(select(ApprovalRecord).where(ApprovalRecord.idempotency_key==idempotency_key))
        if prior:
            if prior.actor_user_id!=user_id: raise InvalidStateTransition('IDEMPOTENCY_KEY_ACTOR_MISMATCH')
            return await session.get(RefundRequest,refund_id)
    if not r or r.status!='pending':raise NotFound('Pending refund not found')
    if decision not in {'approved','rejected'}:raise ValueError('Decision must be approved or rejected')
    if not remarks or not remarks.strip():raise InvalidStateTransition('An official decision rationale is required.')
    f=await session.get(FDR,r.fdr_id);old=r.status;r.status=decision;r.reviewed_by=user_id;r.remarks=remarks
    previous_fdr_status=f.status
    if decision=='approved':f.status=FDRStatus.RELEASED.value
    else:f.status=FDRStatus.VERIFIED.value
    workflow=await sync_legacy_status(session,f,actor_id=user_id,
        event_type='RELEASE_APPROVED' if decision=='approved' else 'RELEASE_REJECTED',
        previous_status=previous_fdr_status,
        lifecycle_override='release_approved' if decision=='approved' else 'release_rejected',
        authorization_override='approved' if decision=='approved' else 'rejected')
    if user_id:
        await record_human_decision(session,f,user_id,'aicte_official','approve' if decision=='approved' else 'reject',
            remarks,request_type='release_refund',refund_request_id=r.id,idempotency_key=idempotency_key)
    institution=await session.get(Institution,f.institution_id)
    if institution and institution.contact_email:
        effect_key=idempotency_key or f'refund-decision:{r.id}:{decision}'
        stage=f'REFUND-DECISION-{effect_key[:80]}'
        if not await session.scalar(select(Notification.id).where(Notification.fdr_id==f.id,
            Notification.stage==stage,Notification.channel=='email')):
            notification=Notification(fdr_id=f.id,stage=stage,channel='email',
                recipient=institution.contact_email,status='queued')
            session.add(notification);await session.flush()
            await enqueue_outbox(session,str(f.id),'DELIVER_NOTIFICATION',
                {'notification_id':notification.id,'channel':'email','recipient':institution.contact_email,
                 'subject':f'AICTE release decision: {f.fdr_number}',
                 'body':f'<p>Decision: {html.escape(decision.title())}</p><p>Official remarks: {html.escape(remarks)}</p>',
                 'template_version':'release-decision-v1'},effect_key)
    await record(session,user_id,'refund',r.id,'decision','',{'status':[old,decision],'remarks':[None,remarks]})
    await record(session,user_id,'fdr',f.id,'released' if decision=='approved' else 'release_rejected','',
        {'status':[previous_fdr_status,f.status]})
    return r


async def list_refunds(session: AsyncSession, status: str | None, institution_id: int | None, page: Pagination) -> list[RefundRequest]:
    query=select(RefundRequest).join(FDR)
    if institution_id is not None: query=query.where(FDR.institution_id==institution_id)
    if status: query=query.where(RefundRequest.status==status)
    query=query.order_by(RefundRequest.id.desc()).offset(page.skip).limit(page.limit)
    return list((await session.scalars(query)).all())
