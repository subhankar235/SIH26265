"""Demo PNB adapter; each bank may use a slightly different response shape to show normalisation."""

from fastapi import APIRouter
from ..models import VerifyRequest
from ..store import lookup

router = APIRouter()


@router.post("/fdr/verify")
async def verify_fdr(body: VerifyRequest):
    # Lookup in store, return PNB-style payload (rename a few fields to demonstrate adapter mapping)
    r=lookup('pnb',body.fdr_number)
    if not r:return {'exists':False}
    return {'exists':True,'fdr_status':r['status'],'principal':r['amount'],'maturity':r['maturity_date'],'customer':r['holder_name']}


@router.get("/fdr/{fdr_number}/status")
async def fdr_status(fdr_number: str):
    # Return status only
    r=lookup('pnb',fdr_number);return {'exists':bool(r),'fdr_status':r['status'] if r else None}
