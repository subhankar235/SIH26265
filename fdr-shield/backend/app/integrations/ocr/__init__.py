from functools import lru_cache

from app.core.config import get_settings
from app.integrations.ocr.base import FdrExtractor


class DisabledOcrEngine:
    """No-provider OCR mode; lets users enter/review fields manually without a network call."""

    async def extract(self, pages: list[bytes]) -> dict:
        return {key: None for key in ('fdr_number', 'bank_name', 'branch', 'holder_name', 'amount', 'issue_date', 'maturity_date')}


@lru_cache(maxsize=1)
def get_engine() -> FdrExtractor:
    engine = get_settings().ocr_engine.strip().lower()
    if engine == 'disabled':
        return DisabledOcrEngine()
    if engine == 'ollama_vision':
        from app.integrations.ocr.ollama_vision_engine import OllamaVisionEngine
        return OllamaVisionEngine()
    if engine == 'easyocr':
        from app.integrations.ocr.easyocr_engine import EasyOcrEngine
        return EasyOcrEngine()
    if engine == 'tesseract':
        from app.integrations.ocr.tesseract_engine import TesseractEngine
        return TesseractEngine()
    if engine == 'cnn':
        from app.integrations.ocr.cnn_engine import CnnEngine
        return CnnEngine()
    raise ValueError(f'Unsupported OCR_ENGINE: {engine}')
