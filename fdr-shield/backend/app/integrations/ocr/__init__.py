from functools import lru_cache

from app.core.config import get_settings
from app.integrations.ocr.base import FdrExtractor


@lru_cache(maxsize=1)
def get_engine() -> FdrExtractor:
    engine = get_settings().ocr_engine.strip().lower()
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
