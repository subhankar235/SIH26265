"""Future engine hook. Implement FdrExtractor.extract when a light CNN is selected."""

from app.integrations.ocr.base import FdrFields


class CnnEngine:
    async def extract(self, pages: list[bytes]) -> FdrFields:
        raise RuntimeError('CNN OCR engine is not configured; select ollama_vision or easyocr')
