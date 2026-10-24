"""Deterministic FDR field validation. No model output can bypass these rules."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.fdr import FDR
from app.models.document import Document
from app.schemas.verification import OcrResult
from app.schemas.workflow import ExtractedField, ExtractionResult, ValidationDiscrepancy, ValidationResult

RULE_VERSION = 'fdr-validation-v1'
REQUIRED_DECLARED = ('fdr_number','bank_name','amount','issue_date','maturity_date','holder')
SUPPORTED_MOCK_BANKS = {'sbi','pnb','hdfc'}


def _normalized(value):
    return ' '.join(str(value).strip().casefold().split()) if value is not None else None


def _decimal(value):
    if value is None: return None
    try:
        return Decimal(str(value).replace(',','')).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _date(value):
    if value is None: return None
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    text=str(value).strip()
    try: return date.fromisoformat(text[:10])
    except (ValueError, TypeError): pass
    from datetime import datetime as _datetime
    for pattern in ('%d/%m/%Y','%d-%m-%Y','%Y/%m/%d'):
        try: return _datetime.strptime(text,pattern).date()
        except ValueError: continue
    return None


def _finding(field, declared, extracted, severity, rule_id, message):
    return ValidationDiscrepancy(field=field,
        declared_value=None if declared is None else str(declared),
        extracted_value=None if extracted is None else str(extracted),
        severity=severity, rule_id=rule_id, rule_version=RULE_VERSION, message=message)


def make_extraction_result(fdr: FDR, document: Document, ocr: OcrResult,
                           extractor_version: str, source_spans: dict | None = None) -> ExtractionResult:
    """Attach per-field trust/confidence and immutable document reference to OCR candidates."""
    aliases = {'holder':'holder_name'}
    fields = {}
    source_spans=source_spans or {}
    for name in ('fdr_number','bank_name','holder','amount','issue_date','maturity_date'):
        value = getattr(ocr, aliases.get(name, name))
        span = source_spans.get(aliases.get(name,name))
        if span and value is not None:
            quote = _normalized(span.get('quote'))
            token = _normalized(value)
            # Reject a locator that does not quote the field value it claims to support.
            if name == 'amount':
                quote_digits=''.join(character for character in str(span.get('quote','')) if character.isdigit())
                token_digits=''.join(character for character in str(value) if character.isdigit())
                supported=bool(token_digits and token_digits in quote_digits)
            elif name in {'issue_date','maturity_date'}:
                import re
                quote_dates=re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}',str(span.get('quote','')))
                supported=any(_date(candidate)==_date(value) for candidate in quote_dates)
            elif name == 'fdr_number':
                alnum=lambda item: ''.join(ch for ch in str(item).casefold() if ch.isalnum())
                supported=bool(alnum(token) and alnum(token) in alnum(quote or ''))
            else:
                supported=bool(quote and token and token in quote)
            if not supported:
                span = None
        fields[name] = ExtractedField(value=value, confidence=float(ocr.confidence),
            source_span=span, trust='extracted')
    return ExtractionResult(fdr_id=fdr.id, document_id=document.id,
        document_version=document.version_no or 1, raw_ref=f'document:{document.id}:{document.sha256 or "unhashed"}',
        extractor_version=extractor_version, fields=fields, overall_confidence=float(ocr.confidence))


async def validate_fdr(session: AsyncSession, fdr: FDR,
                       extraction: ExtractionResult | None = None,
                       *, today: date | None = None) -> ValidationResult:
    """Check declarations, extracted evidence, date/amount rules and duplicate refs."""
    today = today or date.today()
    declared = fdr.declared_data or {}
    extracted = {name: item.value for name,item in (extraction.fields.items() if extraction else [])}
    findings: list[ValidationDiscrepancy] = []
    missing = []
    for field in REQUIRED_DECLARED:
        value = declared.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
            findings.append(_finding(field, None, None, 'high', 'required_declared_field',
                f'The institution-submitted {field.replace("_", " ")} is required.'))
    amount = _decimal(declared.get('amount'))
    if amount is None or amount <= 0:
        findings.append(_finding('amount', declared.get('amount'), extracted.get('amount'), 'high',
            'amount_positive', 'Deposit amount must be a valid positive INR amount.'))
    issue = _date(declared.get('issue_date'))
    maturity = _date(declared.get('maturity_date'))
    if declared.get('issue_date') is not None and issue is None:
        findings.append(_finding('issue_date', declared.get('issue_date'), None, 'high',
            'issue_date_parse', 'Issue date could not be parsed.'))
    if declared.get('maturity_date') is not None and maturity is None:
        findings.append(_finding('maturity_date', declared.get('maturity_date'), None, 'high',
            'maturity_date_parse', 'Maturity date could not be parsed.'))
    if issue and maturity and issue >= maturity:
        findings.append(_finding('maturity_date', issue, maturity, 'high',
            'date_order', 'Maturity date must be later than issue date.'))
    if maturity and maturity < today:
        findings.append(_finding('maturity_date', maturity, None, 'high',
            'not_expired_on_submission', 'A newly submitted FDR must not already be past maturity.'))

    bank = _normalized(declared.get('bank_name'))
    if bank:
        bank_code = bank.split()[0]
        if bank_code not in SUPPORTED_MOCK_BANKS:
            findings.append(_finding('bank_name', declared.get('bank_name'), None, 'low',
                'bank_adapter_unavailable', 'This bank is not available in the demo verification adapter; official scrutiny is required.'))

    number = _normalized(declared.get('fdr_number'))
    if number:
        duplicate_id = await session.scalar(select(FDR.id).where(
            func.lower(FDR.fdr_number) == number, FDR.id != fdr.id).limit(1))
        if duplicate_id:
            findings.append(_finding('fdr_number', declared.get('fdr_number'), str(duplicate_id), 'high',
                'duplicate_instrument_reference', 'This FDR reference is already present in the registry and requires scrutiny.'))

    # OCR candidates are never promoted to external or human verification. Exact numeric/date
    # fields use typed comparisons; text is normalized only for whitespace/case.
    for field in ('fdr_number','bank_name','holder','amount','issue_date','maturity_date'):
        actual = extracted.get('holder_name') if field == 'holder' else extracted.get(field)
        expected = declared.get(field)
        if actual is None:
            if extraction and expected is not None:
                findings.append(_finding(field, expected, None, 'low', 'extraction_missing_field',
                    'The field was not confidently extracted; an authorized reviewer should inspect the document.'))
            continue
        if field == 'amount': equal = _decimal(expected) is not None and _decimal(expected) == _decimal(actual)
        elif field in {'issue_date','maturity_date'}: equal = _date(expected) is not None and _date(expected) == _date(actual)
        else: equal = _normalized(expected) == _normalized(actual)
        if not equal:
            findings.append(_finding(field, expected, actual,
                'high' if field in {'amount','fdr_number'} else 'medium',
                f'declared_extracted_{field}_match',
                f'The declared {field.replace("_", " ")} differs from the document extraction.'))

    blocking = any(item.severity == 'high' for item in findings)
    return ValidationResult(passed=not blocking, rule_version=RULE_VERSION,
        discrepancies=findings, required_fields_missing=missing)
