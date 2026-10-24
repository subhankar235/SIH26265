"""Background OCR + bank verification pipeline (USP 1 & 3)."""

from .celery_app import celery_app, run_async_task
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.fdr import FDR
from app.models.document import Document
from app.integrations import storage_client
from app.services import ocr_service, bank_verification_service, fraud_service, trust_score_service
from app.services.audit_service import record
from app.core.enums import TrustBadge


@celery_app.task(name='app.workers.tasks_verification.run_verification_pipeline',autoretry_for=(Exception,),retry_backoff=True,max_retries=3)
def run_verification_pipeline(fdr_id: int) -> None:
    # @celery_app.task. Steps:
    # 1 download scan from S3
    # 2 ocr_service.extract_fdr_fields -> save fdr.ocr_data
    # 3 bank_verification_service.verify_with_bank -> save fdr.bank_data
    # 4 fraud_service.compare_records + persist_discrepancies
    # 5 trust_score_service.apply_badge
    # 6 audit_service.record(action='auto_verification')
    run_async_task(_run(fdr_id))

async def _run(fdr_id):
    async with SessionLocal() as session:
        f=await session.get(FDR,fdr_id)
        if not f:return
        doc=await session.scalar(select(Document).where(Document.fdr_id==fdr_id,Document.doc_type=='fdr_scan'))
        if not doc:return
        import asyncio
        data=await asyncio.to_thread(storage_client.get,doc.s3_key)
        ocr=await ocr_service.extract_fdr_fields(data,doc.content_type);f.ocr_data=ocr.model_dump(mode='json')
        if ocr.confidence == 0:
            old_badge=f.trust_badge;f.trust_badge=TrustBadge.SELF_DECLARED.value
            await record(session,None,'fdr',f.id,'ocr_unavailable','worker',{'ocr_data':[None,f.ocr_data],'trust_badge':[old_badge,f.trust_badge]})
            await session.commit()
            return
        bank=await bank_verification_service.verify_with_bank(f.bank_name,f.fdr_number,f.declared_data.get('holder',''));f.bank_data=bank.model_dump(mode='json')
        items=await fraud_service.compare_records(f.declared_data,ocr,bank);await fraud_service.persist_discrepancies(session,f.id,items)
        await trust_score_service.apply_badge(session,f.id)
        await record(session,None,'fdr',f.id,'auto_verification','worker',{'ocr_data':[None,f.ocr_data],'bank_data':[None,f.bank_data]})
        await session.commit()
