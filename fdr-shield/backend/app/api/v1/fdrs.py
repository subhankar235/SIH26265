"""FDR lifecycle endpoints."""

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from datetime import date
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles
from app.schemas.fdr import FDRCreate, FDROut, FDRStatusUpdate, RenewalRequest
from app.services import fdr_service, document_service
from app.core.deps import pagination, Pagination
router = APIRouter()


@router.post("")
async def submit_fdr(fdr_number:str=Form(...),bank_name:str=Form(...),branch:str=Form(''),amount:Decimal=Form(...),issue_date:date=Form(...),maturity_date:date=Form(...),holder:str=Form(''),file:UploadFile=File(...),session:AsyncSession=Depends(get_session),user=Depends(require_roles('institution'))):
    data=FDRCreate(fdr_number=fdr_number,bank_name=bank_name,branch=branch,amount=amount,issue_date=issue_date,maturity_date=maturity_date,holder=holder)
    fdr=await fdr_service.create_fdr(session,data,user.institution_id,user.id)
    await document_service.store_upload(session,fdr.id,'fdr_scan',file,user.id)
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
