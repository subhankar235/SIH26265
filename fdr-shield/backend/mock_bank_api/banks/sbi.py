"""Demo SBI adapter; each bank may use a slightly different response shape to show normalisation."""

from fastapi import APIRouter
from ..models import VerifyRequest
from ..store import lookup

router = APIRouter()


@router.post("/fdr/verify")
async def verify_fdr(body: VerifyRequest):
    # Lookup in store, return SBI-style payload (rename a few fields to demonstrate adapter mapping)
    r=lookup('sbi',body.fdr_number)
    if not r:return {'found':False}
    return {'found':True,'status':r['status'],'amount':r['amount'],'maturity_date':r['maturity_date'],'holder_name':r['holder_name']}


@router.get("/fdr/{fdr_number}/status")
async def fdr_status(fdr_number: str):
    # Return status only
    r=lookup('sbi',fdr_number);return {'found':bool(r),'status':r['status'] if r else None}
