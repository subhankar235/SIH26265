"""USP 2 - alert composition & dispatch."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import AlertStage, FDRStatus
from app.models.notification import Notification
from app.models.fdr import FDR
from app.models.user import User
from app.models.institution import Institution
from app.core.deps import Pagination
from app.services.audit_service import record
from sqlalchemy import select
from datetime import datetime, timezone
from app.integrations.email_client import send_email
from app.integrations.telegram_client import send_message
from app.integrations.whatsapp_mock import send_whatsapp


async def stage_for(days_left: int) -> AlertStage | None:
    # <=0 T_0, <=30 T_30, <=90 T_90 else None
    if days_left<=0:return AlertStage.T_0
    if days_left<=30:return AlertStage.T_30
    if days_left<=90:return AlertStage.T_90
    return None


async def dispatch_alert(session: AsyncSession, fdr: FDR, stage: AlertStage) -> None:
    # Skip if Notification already exists for (fdr, stage); send via email_client + telegram_client + whatsapp_mock; store rows
    stage=getattr(stage,'value',stage)
    if await session.scalar(select(Notification.id).where(Notification.fdr_id==fdr.id,Notification.stage==stage)):return
    inst=await session.get(Institution,fdr.institution_id);subject,body=await render_template(AlertStage(stage),fdr)
    channels=[('email',inst.contact_email,await send_email(inst.contact_email,subject,body)),('whatsapp_mock',inst.contact_phone,await send_whatsapp(inst.contact_phone,subject))]
    if inst.telegram_chat_id:channels.append(('telegram',inst.telegram_chat_id,await send_message(inst.telegram_chat_id,subject)))
    sent_at=datetime.now(timezone.utc).replace(tzinfo=None)
    for channel,to,ok in channels:session.add(Notification(fdr_id=fdr.id,stage=stage,channel=channel,recipient=to,status='sent' if ok else 'failed',sent_at=sent_at if ok else None))
    previous_stage=fdr.last_alert_stage
    fdr.last_alert_stage=stage
    await record(session,None,'fdr',fdr.id,'alert_dispatched','system',{'last_alert_stage':[previous_stage,stage]})


async def escalate_to_bureau(session: AsyncSession, fdr: FDR) -> None:
    # On T-0 with no renewal: mark ESCALATED, notify bureau chief users
    previous_status=fdr.status
    fdr.status=FDRStatus.EXPIRED.value if fdr.maturity_date.isoformat() < datetime.now(timezone.utc).date().isoformat() else fdr.status
    if previous_status!=fdr.status:
        await record(session,None,'fdr',fdr.id,'expired','scheduler',{'status':[previous_status,fdr.status]})
    chiefs=(await session.scalars(select(User).where(User.role=='bureau_chief',User.is_active.is_(True)))).all()
    if chiefs and not await session.scalar(select(Notification.id).where(
        Notification.fdr_id==fdr.id,Notification.stage==AlertStage.ESCALATED.value,Notification.channel=='email'
    )):
        inst=await session.get(Institution,fdr.institution_id)
        recipients=', '.join(user.email for user in chiefs)
        subject=f'Bureau escalation: FDR {fdr.fdr_number} has matured'
        body=f'<p>FDR {fdr.fdr_number} at {fdr.bank_name} matured on {fdr.maturity_date}.</p><p>Institution: {inst.name if inst else fdr.institution_id}</p>'
        ok=await send_email(recipients,subject,body)
        session.add(Notification(fdr_id=fdr.id,stage=AlertStage.ESCALATED.value,channel='email',recipient=recipients,
            status='sent' if ok else 'failed',sent_at=datetime.now(timezone.utc).replace(tzinfo=None) if ok else None))
    await record(session,None,'fdr',fdr.id,'bureau_escalation','system',{'stage':[None,AlertStage.ESCALATED.value]})


async def render_template(stage: AlertStage, fdr: FDR) -> tuple[str, str]:
    # Return (subject, body) from integrations/templates
    return (f'FDR maturity alert: {stage.value}',f'<p>FDR {fdr.fdr_number} at {fdr.bank_name} matures on {fdr.maturity_date}.</p><p>Amount: INR {fdr.amount}</p>')


async def list_notifications(session: AsyncSession, fdr_id: int | None, institution_id: int | None, page: Pagination) -> list[Notification]:
    query = select(Notification).join(FDR)
    if fdr_id is not None: query = query.where(Notification.fdr_id == fdr_id)
    if institution_id is not None: query = query.where(FDR.institution_id == institution_id)
    query = query.order_by(Notification.id.desc()).offset(page.skip).limit(page.limit)
    return list((await session.scalars(query)).all())
