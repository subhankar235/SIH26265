"""FDR lifecycle endpoints."""

import logging

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from datetime import date
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles, get_client_ip
from app.schemas.fdr import FDRCreate, FDROut, FDRStatusUpdate, RenewalRequest
from app.services import fdr_service, document_service
from app.core.deps import pagination, Pagination
router = APIRouter()
logger = logging.getLogger(__name__)


@router.post('/extract-preview')
async def extract_preview(request: Request, file: UploadFile = File(...), user=Depends(require_roles('institution'))):
    """Extract a scan before submission; never persists or creates an FDR."""
    from app.services.rate_limit_service import enforce_rate_limit
    from app.core.config import get_settings
    await enforce_rate_limit('ocr-preview',f'{user.id}:{get_client_ip(request)}',get_settings().rate_limit_ocr_per_minute,60)
    if file.content_type not in {'application/pdf', 'image/jpeg', 'image/png'}:
        raise HTTPException(415, 'Only PDF, JPEG, and PNG files are accepted')
    data = await file.read()
    signatures = {'application/pdf': data.startswith(b'%PDF-'),
                  'image/jpeg': data.startswith(b'\xff\xd8\xff'),
                  'image/png': data.startswith(b'\x89PNG\r\n\x1a\n')}
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, 'File must be between 1 byte and 10 MB')
    if not signatures[file.content_type]:
        raise HTTPException(415, 'File contents do not match the declared file type')
    from app.integrations.upload_scanner import scan_upload
    await scan_upload(data)
    from app.services.ocr_service import extract_fdr_fields
    try:
        extracted = await extract_fdr_fields(data, file.content_type, raise_errors=True)
    except Exception as exc:
        logger.exception('FDR OCR preview failed')
        raise HTTPException(
            502,
            'OCR provider failed. Check the backend log; you can enter the fields manually.',
        ) from exc
    fields = {
        'fdr_number': extracted.fdr_number,
        'bank_name': extracted.bank_name,
        'branch': extracted.branch,
        'amount': str(extracted.amount) if extracted.amount is not None else None,
        'issue_date': extracted.issue_date.isoformat() if extracted.issue_date else None,
        'maturity_date': extracted.maturity_date.isoformat() if extracted.maturity_date else None,
        'holder': extracted.holder_name,
    }
    # OCR adapter currently exposes document-level confidence; present a conservative
    # per-field badge based on presence and the documented overall confidence score.
    confidence = {name: (float(extracted.confidence) if value not in (None, '') else 0.0)
                  for name, value in fields.items()}
    return {'fields': fields, 'confidence': confidence,
            'format_check': {'status': extracted.document_format, 'reason': extracted.format_reason},
            'low_confidence_threshold': 0.7,
            'message': 'Missing values are not inferred; verify every field against the scan.'}


@router.post("")
async def submit_fdr(request:Request,fdr_number:str=Form(...),bank_name:str=Form(...),branch:str=Form(''),amount:Decimal=Form(...),issue_date:date=Form(...),maturity_date:date=Form(...),holder:str=Form(''),file:UploadFile=File(...),confirmed_fields:str|None=Form(None),field_provenance:str|None=Form(None),session:AsyncSession=Depends(get_session),user=Depends(require_roles('institution'))):
    from app.services.rate_limit_service import enforce_rate_limit
    from app.core.config import get_settings
    await enforce_rate_limit('fdr-submit',f'{user.id}:{get_client_ip(request)}',get_settings().rate_limit_ocr_per_minute,60)
    data=FDRCreate(fdr_number=fdr_number,bank_name=bank_name,branch=branch,amount=amount,issue_date=issue_date,maturity_date=maturity_date,holder=holder)
    fdr=await fdr_service.create_fdr(session,data,user.institution_id,user.id)
    if confirmed_fields is not None:
        import json
        required = {'fdr_number', 'bank_name', 'branch', 'amount', 'issue_date', 'maturity_date', 'holder'}
        try:
            confirmed_raw = json.loads(confirmed_fields)
            provenance = json.loads(field_provenance or '{}')
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, 'Invalid field confirmation metadata') from exc
        if not isinstance(confirmed_raw, list) or not isinstance(provenance, dict):
            raise HTTPException(422, 'Invalid field confirmation metadata')
        try:
            confirmed = set(confirmed_raw)
        except TypeError as exc:
            raise HTTPException(422, 'Invalid field confirmation metadata') from exc
        if confirmed != required or set(provenance) != required or any(v not in {'EXTRACTED', 'DECLARED'} for v in provenance.values()):
            raise HTTPException(422, 'Every field must be confirmed and have EXTRACTED or DECLARED provenance')
        fdr.declared_data = {**fdr.declared_data, '_field_provenance': provenance,
                             '_confirmed_fields': sorted(confirmed)}
        from app.services.audit_service import record
        await record(session, user.id, 'fdr', fdr.id, 'field_provenance_confirmed', '',
                     {'field_provenance': [None, provenance], 'confirmed_fields': [None, sorted(confirmed)]})
    await document_service.store_upload(session,fdr.id,'fdr_scan',file,user.id)
    from app.services.local_execution_service import run_inline_workflow_if_enabled
    if await run_inline_workflow_if_enabled(session, fdr.id):
        await session.refresh(fdr)
    return {'id':fdr.id,'fdr_id':fdr.id,'status':fdr.status,'trust_badge':fdr.trust_badge,
            'lifecycle_state':fdr.lifecycle_state,'execution_state':fdr.execution_state}


@router.get("")
async def list_fdrs(status: str | None = None, badge: str | None = None, institution_id: int | None = None, page: Pagination = Depends(pagination), session=Depends(get_session), user=Depends(get_current_user)):
    # Filterable Trust Matrix data; institution role is auto-scoped to own FDRs
    scope=user.institution_id if user.role=='institution' else institution_id
    return await fdr_service.list_fdrs(session,{'status':status,'trust_badge':badge,'institution_id':institution_id},scope,page)


@router.get("/{fdr_id}")
async def get_fdr(fdr_id: int, session=Depends(get_session), user=Depends(get_current_user)):
    # FDR detail incl. declared/ocr/bank data side-by-side + discrepancies
    scope=user.institution_id if user.role=='institution' else None
    return await fdr_service.get_fdr(session,fdr_id,scope)


@router.patch("/{fdr_id}/status")
async def update_status(fdr_id: int, body: FDRStatusUpdate, session=Depends(get_session), user=Depends(require_roles('aicte_official'))):
    # Validate transition via fdr_service.transition; write audit
    return await fdr_service.transition(session,fdr_id,body.status,user.id,body.remarks)


@router.post("/{fdr_id}/renewal")
async def request_renewal(fdr_id: int, body: RenewalRequest, session=Depends(get_session), user=Depends(require_roles('institution'))):
    # Create replacement FDR linked by replaces_fdr_id; set old one RENEWAL_REQUESTED
    scope=user.institution_id if user.role=='institution' else None
    return await fdr_service.request_renewal(session,fdr_id,body,user.id,scope)


@router.get("/{fdr_id}/presigned-url")
async def get_presigned_url(fdr_id: int, session=Depends(get_session), user=Depends(get_current_user)):
    # Return short-lived (5 min) presigned S3 URL for the scan (SplitViewer left pane)
    scope=user.institution_id if user.role=='institution' else None
    await fdr_service.get_fdr(session,fdr_id,scope)
    return {'url':await document_service.get_presigned_url(session,fdr_id)}
