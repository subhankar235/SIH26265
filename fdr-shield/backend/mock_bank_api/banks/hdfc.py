"""Demo HDFC adapter; each bank may use a slightly different response shape to show normalisation."""

from fastapi import APIRouter
from ..models import VerifyRequest
from ..store import lookup

router = APIRouter()


@router.post("/fdr/verify")
async def verify_fdr(body: VerifyRequest):
    # Lookup in store, return HDFC-style payload (rename a few fields to demonstrate adapter mapping)
    r=lookup('hdfc',body.fdr_number)
    if not r:return {'valid':False}
    return {'valid':True,'state':r['status'],'deposit_amount':r['amount'],'maturity_date':r['maturity_date'],'holder_name':r['holder_name']}


@router.get("/fdr/{fdr_number}/status")
async def fdr_status(fdr_number: str):
    # Return status only
    r=lookup('hdfc',fdr_number);return {'valid':bool(r),'state':r['status'] if r else None}
