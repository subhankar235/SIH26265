"""Optional Tesseract adapter; Python binding loads only when explicitly selected."""
import asyncio
import io
from PIL import Image
from app.integrations.ocr.base import FdrFields

def read_text(image_bytes: bytes) -> str:
    import pytesseract
    return pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))

class TesseractEngine:
    async def extract(self,pages:list[bytes])->FdrFields:
        from app.services.ocr_service import parse_fdr_text
        text='\n'.join([await asyncio.to_thread(read_text,p) for p in pages[:2]])
        result=await parse_fdr_text(text)
        return {'fdr_number':result.fdr_number,'bank_name':result.bank_name,'branch':result.branch,'holder_name':result.holder_name,'amount':float(result.amount) if result.amount is not None else None,'issue_date':result.issue_date.isoformat() if result.issue_date else None,'maturity_date':result.maturity_date.isoformat() if result.maturity_date else None}
