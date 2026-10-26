"""USP 1 - compare declared vs OCR vs bank data."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from rapidfuzz.fuzz import token_set_ratio
from app.schemas.verification import DiscrepancyOut
from app.models.discrepancy import Discrepancy
from sqlalchemy import delete
from app.schemas.verification import OcrResult, BankVerifyResponse
from decimal import Decimal, InvalidOperation


async def compare_records(declared: dict, ocr: OcrResult | None, bank: BankVerifyResponse | None) -> list[DiscrepancyOut]:
    # Per-field compare; amount exact, dates exact, bank name & holder fuzzy via rapidfuzz (>=85)
    result=[]
    ocr_values=ocr.model_dump() if ocr else {}
    if ocr_values.get('holder_name') is not None: ocr_values['holder']=ocr_values['holder_name']
    if not any(ocr_values.get(key) is not None for key in ('fdr_number','bank_name','holder_name','amount','issue_date','maturity_date')):
        return []
    sources=[('ocr',ocr_values),('bank_api',bank.model_dump() if bank else {})]
    keys=('fdr_number','amount','maturity_date','bank_name','holder')
    for source,record in sources:
        if source=='bank_api' and not record.get('found'): continue
        for field in keys:
            left=declared.get(field); right=record.get(field)
            if left is None or right is None: continue
            a=str(left); b=str(right)
            if field in ('bank_name','holder'):
                equal=token_set_ratio(a,b)>=85
            elif field=='amount':
                try: equal=Decimal(a).quantize(Decimal('0.01'))==Decimal(b).quantize(Decimal('0.01'))
                except (InvalidOperation,ValueError): equal=False
            else:
                equal=a==b
            if not equal: result.append(DiscrepancyOut(field=field,declared_value=a,extracted_value=b,source=source,severity=await severity_for(field,a,b)))
    return result


async def persist_discrepancies(session: AsyncSession, fdr_id: int, items: list[DiscrepancyOut],
                                validation_findings: list | None = None) -> None:
    # Replace unresolved rows for this verification pass; retain resolved history.
    await session.execute(delete(Discrepancy).where(Discrepancy.fdr_id==fdr_id,Discrepancy.resolved.is_(False)))
    rows=[]
    seen=set()
    for finding in items:
        key=(finding.field,finding.source,finding.declared_value,finding.extracted_value)
        if key in seen: continue
        seen.add(key)
        rows.append(Discrepancy(fdr_id=fdr_id,field=finding.field,declared_value=finding.declared_value or '',
            extracted_value=finding.extracted_value or '',source=finding.source,severity=finding.severity,resolved=False))
    for finding in validation_findings or []:
        key=(finding.field,finding.source,finding.declared_value,finding.extracted_value)
        if key in seen: continue
        seen.add(key)
        rows.append(Discrepancy(fdr_id=fdr_id,field=finding.field,declared_value=finding.declared_value or '',
            extracted_value=finding.extracted_value or '',source=finding.source,severity=finding.severity,
            rule_id=finding.rule_id,rule_version=finding.rule_version,resolved=False))
    session.add_all(rows)


async def severity_for(field: str, declared: str, found: str) -> str:
    # amount/fdr_number mismatch = high, others = low
    return 'high' if field in ('fdr_number','amount') else 'low'
