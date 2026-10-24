"""Optional EasyOCR adapter; heavy libraries load only when explicitly selected."""
import asyncio
import io
from PIL import Image
from app.integrations.ocr.base import FdrFields

def read_text(image_bytes: bytes) -> str:
    import easyocr
    import numpy as np
    global _reader
    if '_reader' not in globals(): _reader=easyocr.Reader(['en'],gpu=False)
    return '\n'.join(_reader.readtext(np.asarray(Image.open(io.BytesIO(image_bytes)).convert('RGB')),detail=0))

class EasyOcrEngine:
    async def extract(self,pages:list[bytes])->FdrFields:
        from app.services.ocr_service import parse_fdr_text
        text='\n'.join([await asyncio.to_thread(read_text,p) for p in pages[:2]])
        result=await parse_fdr_text(text)
        return {'fdr_number':result.fdr_number,'bank_name':result.bank_name,'holder_name':result.holder_name,'amount':float(result.amount) if result.amount is not None else None,'issue_date':result.issue_date.isoformat() if result.issue_date else None,'maturity_date':result.maturity_date.isoformat() if result.maturity_date else None}
