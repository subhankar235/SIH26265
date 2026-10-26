"""OCR orchestration and validation. Extraction errors intentionally degrade to empty data."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.integrations.ocr import get_engine
from app.schemas.verification import OcrResult

logger = logging.getLogger(__name__)


async def extract_fdr_fields(file_bytes: bytes, content_type: str, *, raise_errors: bool = False) -> OcrResult:
    try:
        pages = await _to_pages(file_bytes, content_type)
        values = await get_engine().extract(pages)
        result = OcrResult(
            fdr_number=_optional_text(values.get('fdr_number')),
            bank_name=_optional_text(values.get('bank_name')),
            branch=_optional_text(values.get('branch')),
            holder_name=_optional_text(values.get('holder_name')),
            amount=_amount(values.get('amount')),
            issue_date=_parse_date(values.get('issue_date')),
            maturity_date=_parse_date(values.get('maturity_date')),
            confidence=0,
        )
        found = sum(getattr(result, field) is not None for field in (
            'fdr_number', 'bank_name', 'branch', 'holder_name', 'amount', 'issue_date', 'maturity_date'
        ))
        result.confidence = found / 7
        return result
    except Exception:
        logger.exception('FDR OCR extraction failed; leaving the record unverified')
        if raise_errors:
            raise
        return OcrResult(confidence=0)


async def extract_source_spans(file_bytes: bytes, content_type: str, fields: dict) -> dict:
    """Optional locator references from adapters that can return grounded page quotes."""
    try:
        pages=await _to_pages(file_bytes,content_type)
        engine=get_engine()
        method=getattr(engine,'extract_source_spans',None)
        if not method: return {}
        return await method(pages,fields)
    except Exception:
        logger.exception('OCR evidence-locator extraction failed; retaining field values without spans')
        return {}


async def _to_pages(file_bytes: bytes, content_type: str) -> list[bytes]:
    if content_type == 'application/pdf':
        from pdf2image import convert_from_bytes
        images = await asyncio.to_thread(convert_from_bytes, file_bytes, first_page=1, last_page=2)
        pages=[]
        for image in images[:2]:
            output=BytesIO(); image.convert('RGB').save(output,format='JPEG',quality=90); pages.append(output.getvalue())
        return pages
    with Image.open(BytesIO(file_bytes)) as image:
        output=BytesIO(); ImageOps.exif_transpose(image).convert('RGB').save(output,format='JPEG',quality=90)
        return [output.getvalue()]


def _optional_text(value: object) -> str | None:
    if value is None: return None
    text=str(value).strip()
    return text or None


def _amount(value: object) -> Decimal | None:
    if value is None or value == '': return None
    try:
        cleaned=re.sub(r'[^0-9.]','',str(value).replace(',',''))
        return Decimal(cleaned) if cleaned else None
    except (InvalidOperation,ValueError):
        return None


def _parse_date(value: object) -> date | None:
    if value is None or value == '': return None
    if isinstance(value,date): return value
    text=str(value).strip()
    for pattern in ('%Y-%m-%d','%d-%m-%Y','%d/%m/%Y','%Y/%m/%d'):
        try: return datetime.strptime(text,pattern).date()
        except ValueError: continue
    return None


async def parse_fdr_text(raw_text: str) -> OcrResult:
    """Small heuristic parser used by the optional EasyOCR/Tesseract adapters."""
    number=re.search(r'\b[A-Z]{2,5}\d{5,}\b',raw_text,re.I)
    amount=re.search(r'(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)',raw_text,re.I)
    dates=re.findall(r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b',raw_text)
    bank=next((name for name in ('SBI','PNB','HDFC') if name.lower() in raw_text.lower()),None)
    branch_match=re.search(
        r'(?im)^\s*(?:(?:bank|home|issuing|local)\s+)?branch(?:\s*/\s*office|\s+name)?\s*[:\-]\s*(.+?)\s*$',
        raw_text,
    )
    holder_match=re.search(r'(?:holder|in the name of|name of depositor)\s*[:\-]?\s*([^\n\r]+)',raw_text,re.I)
    result=OcrResult(
        fdr_number=number.group(0).upper() if number else None,
        bank_name=bank,
        branch=_optional_text(branch_match.group(1)) if branch_match else None,
        holder_name=holder_match.group(1).strip() if holder_match else None,
        amount=_amount(amount.group(1)) if amount else None,
        issue_date=_parse_date(dates[0]) if dates else None,
        maturity_date=_parse_date(dates[1]) if len(dates)>1 else None,
        confidence=0,
    )
    result.confidence=sum(getattr(result,key) is not None for key in ('fdr_number','bank_name','branch','holder_name','amount','issue_date','maturity_date'))/7
    return result


async def preprocess_image(image: bytes) -> bytes:
    with Image.open(BytesIO(image)) as original:
        image=ImageOps.autocontrast(ImageOps.exif_transpose(original).convert('L')).filter(ImageFilter.MedianFilter(3))
        image=ImageEnhance.Contrast(image).enhance(1.5)
        output=BytesIO(); image.save(output,format='PNG'); return output.getvalue()
