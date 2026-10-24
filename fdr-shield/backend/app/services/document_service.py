"""File handling around S3/MinIO."""

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import UploadFile
from fastapi import HTTPException
from app.models.document import Document
from app.models.workflow import CorrectionRequest, WorkflowInstance
from app.models.fdr import FDR
from app.integrations import storage_client
from sqlalchemy import select
from app.services.audit_service import record
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from uuid import uuid4
from app.core.enums import ExecutionState, LifecycleState
from app.services.workflow_events import publish
from app.services.outbox_service import enqueue as enqueue_outbox


async def store_upload(session: AsyncSession, fdr_id: int, doc_type: str, file: UploadFile, user_id: int) -> Document:
    # Validate mime (pdf/jpg/png) & size<=10MB; storage_client.put; insert Document
    allowed={'application/pdf','image/jpeg','image/png'}
    if file.content_type not in allowed: raise HTTPException(415,'Only PDF, JPEG, and PNG files are accepted')
    data=await file.read()
    if not data or len(data)>10*1024*1024: raise HTTPException(413,'File must be between 1 byte and 10 MB')
    signatures={
        'application/pdf': data.startswith(b'%PDF-'),
        'image/jpeg': data.startswith(b'\xff\xd8\xff'),
        'image/png': data.startswith(b'\x89PNG\r\n\x1a\n'),
    }
    if not signatures.get(file.content_type,False): raise HTTPException(415,'File contents do not match the declared file type')
    existing = list((await session.scalars(select(Document).where(
        Document.fdr_id == fdr_id, Document.doc_type == doc_type).order_by(Document.id))).all())
    previous = existing[-1] if existing else None
    version_no = max(len(existing), max((row.version_no or 0 for row in existing), default=0)) + 1
    safe_filename = Path(file.filename or 'upload').name.replace('..', '_')
    digest = hashlib.sha256(data).hexdigest()
    key=f'{fdr_id}/{doc_type}/v{version_no}/{uuid4().hex}-{safe_filename}'
    import asyncio
    await asyncio.to_thread(storage_client.put,key,data,file.content_type)
    doc=Document(fdr_id=fdr_id,doc_type=doc_type,s3_key=key,content_type=file.content_type,
        uploaded_by=user_id,version_no=version_no,sha256=digest,
        supersedes_document_id=previous.id if previous else None,uploaded_at=datetime.now(timezone.utc))
    session.add(doc);await session.flush()
    await record(session,user_id,'document',doc.id,'uploaded','',
        {'fdr_id':[None,fdr_id],'doc_type':[None,doc_type],'version_no':[None,version_no],'sha256':[None,digest]})
    if doc_type == 'fdr_scan':
        workflow = await session.scalar(select(WorkflowInstance).where(
            WorkflowInstance.fdr_id == fdr_id).order_by(WorkflowInstance.execution_version.desc()).limit(1))
        if workflow and workflow.execution_state == ExecutionState.WAITING_EVENT.value:
            correction = await session.scalar(select(CorrectionRequest).where(
                CorrectionRequest.workflow_instance_id == workflow.id,
                CorrectionRequest.status == 'open').order_by(CorrectionRequest.id.desc()).limit(1))
            if correction:
                correction.status = 'submitted'
                correction.responded_at = datetime.now(timezone.utc)
                workflow.lifecycle_state = LifecycleState.EXTRACTION_PENDING.value
                workflow.execution_state = ExecutionState.RUNNING.value
                workflow.current_node = 'extract_document'
                workflow.worker_lease_until = None
                workflow.version += 1
                fdr = await session.get(FDR, fdr_id)
                if fdr:
                    fdr.lifecycle_state = LifecycleState.EXTRACTION_PENDING.value
                    fdr.execution_state = ExecutionState.RUNNING.value
                await publish(session, workflow.id, 'CORRECTION_RECEIVED',
                    {'document_id': doc.id, 'document_version': version_no, 'sha256': digest},
                    f'correction:{correction.id}:document:{digest}')
                await enqueue_outbox(session, str(workflow.id), 'WORKFLOW_WAKE',
                    {'workflow_instance_id': workflow.id, 'document_id': doc.id},
                    f'workflow:{workflow.id}:correction-document:{digest}')
    return doc


async def get_presigned_url(session: AsyncSession, fdr_id: int, doc_type: str = 'fdr_scan') -> str:
    # storage_client.presign(key, expires=300)
    doc=await session.scalar(select(Document).where(Document.fdr_id==fdr_id,Document.doc_type==doc_type).order_by(Document.id.desc()))
    if not doc: raise HTTPException(404,'Document not found')
    import asyncio
    return await asyncio.to_thread(storage_client.presign,doc.s3_key,300)
