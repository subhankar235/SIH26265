"""USP 3 - calls the DEMO bank gateway (mock_bank_api)."""

import httpx
import logging
from app.core.config import get_settings
from app.schemas.verification import BankVerifyResponse

logger = logging.getLogger(__name__)

async def verify_with_bank(bank_name: str, fdr_number: str, holder: str) -> BankVerifyResponse:
    parts=bank_name.strip().lower().split(maxsplit=1)
    bank=parts[0] if parts else ''
    if bank not in {'sbi','pnb','hdfc'}:
        return BankVerifyResponse(found=False,verification_status='unsupported_bank',
            verification_message=f'The demo gateway does not support {bank_name}; independent bank verification is not configured.')
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r=await client.post(f"{get_settings().mock_bank_url}/{bank}/v1/fdr/verify",json={'fdr_number':fdr_number,'holder_name':holder});r.raise_for_status();data=r.json()
        if not isinstance(data,dict):
            raise ValueError('Demo bank response must be a JSON object')
        found=data.get('found') is True
        return BankVerifyResponse(found=found,status=data.get('status'),amount=data.get('amount'),
            maturity_date=data.get('maturity_date'),holder=data.get('holder_name'),
            verification_status='matched' if found else 'no_match',
            verification_message='Demo bank fixture matched; this is not independent bank confirmation.' if found
                else 'No matching record was found in the demo bank gateway; this is not an independent bank lookup.')
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning('Demo bank verification unavailable (%s).', type(exc).__name__)
        return BankVerifyResponse(found=False,verification_status='gateway_unavailable',
            verification_message='The demo bank gateway could not be reached; independent bank verification is not configured.')


async def list_supported_banks() -> list[str]:
    # GET {MOCK_BANK_URL}/banks
    async with httpx.AsyncClient(timeout=5) as client:
        try:r=await client.get(f"{get_settings().mock_bank_url}/banks");r.raise_for_status();return r.json()
        except Exception:return ['sbi','pnb','hdfc']
