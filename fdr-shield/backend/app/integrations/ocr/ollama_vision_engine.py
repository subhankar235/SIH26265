"""Vision extraction through Ollama's local or cloud-compatible API."""

from __future__ import annotations

import base64
import json
import logging
from io import BytesIO

import httpx
from PIL import Image, ImageOps

from app.core.config import get_settings
from app.integrations.ocr.base import FdrFields

logger = logging.getLogger(__name__)

FIELDS = ('fdr_number', 'bank_name', 'holder_name', 'amount', 'issue_date', 'maturity_date')
JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'fdr_number': {'type': ['string', 'null']},
        'bank_name': {'type': ['string', 'null']},
        'holder_name': {'type': ['string', 'null']},
        'amount': {'type': ['number', 'null']},
        'issue_date': {'type': ['string', 'null']},
        'maturity_date': {'type': ['string', 'null']},
    },
    'required': list(FIELDS),
    'additionalProperties': False,
}
PROMPT = (
    'You are a document-extraction system for Indian Fixed Deposit Receipts; '
    'extract the six fields exactly as printed; amount as a plain number in INR; '
    'dates as YYYY-MM-DD; never guess, use null; return ONLY the JSON object.'
)


class OllamaVisionEngine:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    @staticmethod
    def _to_jpeg(image_bytes: bytes) -> str:
        with Image.open(BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format='JPEG', quality=85, optimize=True)
        return base64.b64encode(output.getvalue()).decode('ascii')

    @staticmethod
    def _normalize(payload: object) -> FdrFields:
        if not isinstance(payload, dict):
            raise ValueError('OCR response must be a JSON object')
        return {key: payload.get(key) for key in FIELDS}  # type: ignore[return-value]

    async def extract(self, pages: list[bytes]) -> FdrFields:
        if not pages:
            return {key: None for key in FIELDS}  # type: ignore[return-value]
        settings = get_settings()
        headers = {'Authorization': f'Bearer {settings.ollama_api_key}'} if settings.ollama_api_key else {}
        body = {
            'model': settings.ollama_model,
            'stream': False,
            'format': JSON_SCHEMA,
            'options': {'temperature': 0},
            'messages': [{'role': 'user', 'content': PROMPT, 'images': [self._to_jpeg(page) for page in pages[:2]]}],
        }
        async with httpx.AsyncClient(timeout=settings.ollama_timeout, transport=self.transport) as client:
            for attempt in range(2):
                response = await client.post(f'{settings.ollama_base_url.rstrip("/")}/api/chat', json=body, headers=headers)
                response.raise_for_status()
                content = response.json().get('message', {}).get('content', '')
                try:
                    cleaned = content.strip()
                    if cleaned.startswith('```'):
                        cleaned = cleaned.split('\n', 1)[1] if '\n' in cleaned else cleaned[3:]
                        if cleaned.rstrip().endswith('```'):
                            cleaned = cleaned.rstrip()[:-3].strip()
                    return self._normalize(json.loads(cleaned))
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    if attempt:
                        raise ValueError('Ollama returned invalid FDR JSON twice') from exc
                    logger.warning('Ollama OCR returned invalid JSON; retrying once')
        raise ValueError('Ollama returned no OCR result')
