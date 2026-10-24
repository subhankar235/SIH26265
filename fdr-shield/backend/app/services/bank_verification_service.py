"""USP 3 - calls the DEMO bank gateway (mock_bank_api)."""

from sqlalchemy.ext.asyncio import AsyncSession
import httpx
from app.core.config import get_settings
from app.schemas.verification import BankVerifyResponse


async def verify_with_bank(bank_name: str, fdr_number: str, holder: str) -> BankVerifyResponse:
    # httpx POST {MOCK_BANK_URL}/{bank}/v1/fdr/verify; map errors to found=False
    bank=bank_name.lower().split()[0]
    if bank not in {'sbi','pnb','hdfc'}: return BankVerifyResponse(found=False)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r=await client.post(f"{get_settings().mock_bank_url}/{bank}/v1/fdr/verify",json={'fdr_number':fdr_number,'holder_name':holder});r.raise_for_status();data=r.json()
        return BankVerifyResponse(found=data.get('found',False),status=data.get('status'),amount=data.get('amount'),maturity_date=data.get('maturity_date'),holder=data.get('holder_name'))
    except Exception: return BankVerifyResponse(found=False)


async def list_supported_banks() -> list[str]:
    # GET {MOCK_BANK_URL}/banks
    async with httpx.AsyncClient(timeout=5) as client:
        try:r=await client.get(f"{get_settings().mock_bank_url}/banks");r.raise_for_status();return r.json()
        except Exception:return ['sbi','pnb','hdfc']
