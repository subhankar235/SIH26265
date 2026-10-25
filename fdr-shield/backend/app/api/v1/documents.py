"""Extra documents (pledge letter, sanction PDF)."""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles, get_client_ip
from app.services import document_service
from app.services import fdr_service
from app.integrations import storage_client

router = APIRouter()


@router.get('/local/{token}')
async def read_local_document(token: str):
    """Serve a short-lived signed document URL when STORAGE_BACKEND=local."""
    try: data = storage_client.read_local_token(token)
    except ValueError as exc: raise HTTPException(403, 'Document link expired or invalid') from exc
    content_type = 'application/pdf' if data.startswith(b'%PDF-') else ('image/png' if data.startswith(b'\x89PNG') else 'image/jpeg')
    return Response(data, media_type=content_type, headers={'Content-Disposition': 'inline'})


@router.post("/{fdr_id}")
async def upload_document(fdr_id: int, request: Request, doc_type: str, file: UploadFile = File(...), session=Depends(get_session), user=Depends(get_current_user)):
    # Validate type/size, store to S3, create Document row
    scope=user.institution_id if user.role=='institution' else None
    await fdr_service.get_fdr(session,fdr_id,scope)
    from app.services.rate_limit_service import enforce_rate_limit
    await enforce_rate_limit('document-upload',f'{user.id}:{get_client_ip(request)}',20,60)
    return await document_service.store_upload(session,fdr_id,doc_type,file,user.id)


@router.get("/{fdr_id}")
async def list_documents(fdr_id: int, session=Depends(get_session), user=Depends(get_current_user)):
    # List documents with presigned URLs
    scope=user.institution_id if user.role=='institution' else None
    await fdr_service.get_fdr(session,fdr_id,scope)
    return {'url':await document_service.get_presigned_url(session,fdr_id)}
