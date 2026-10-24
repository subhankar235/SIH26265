"""File handling around S3/MinIO."""

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import UploadFile
from fastapi import HTTPException
from app.models.document import Document
from app.integrations import storage_client
from sqlalchemy import select
from app.services.audit_service import record


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
    key=f'{fdr_id}/{doc_type}/{user_id}-{file.filename or "upload"}'
    import asyncio
    await asyncio.to_thread(storage_client.put,key,data,file.content_type)
    doc=Document(fdr_id=fdr_id,doc_type=doc_type,s3_key=key,content_type=file.content_type,uploaded_by=user_id);session.add(doc);await session.flush()
    await record(session,user_id,'document',doc.id,'uploaded','',{'fdr_id':[None,fdr_id],'doc_type':[None,doc_type]})
    return doc


async def get_presigned_url(session: AsyncSession, fdr_id: int, doc_type: str = 'fdr_scan') -> str:
    # storage_client.presign(key, expires=300)
    doc=await session.scalar(select(Document).where(Document.fdr_id==fdr_id,Document.doc_type==doc_type).order_by(Document.id.desc()))
    if not doc: raise HTTPException(404,'Document not found')
    import asyncio
    return await asyncio.to_thread(storage_client.presign,doc.s3_key,300)
