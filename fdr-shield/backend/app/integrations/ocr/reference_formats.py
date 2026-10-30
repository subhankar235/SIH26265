"""Cached genuine bank-format references and exact-match negative fixtures."""
from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_BANKS = ('sbi', 'hdfc', 'pnb')


def _root() -> Path:
    configured = Path(get_settings().ocr_reference_dir)
    return configured if configured.is_absolute() else Path(__file__).resolve().parents[3] / configured


@lru_cache(maxsize=8)
def _load_references(root: str) -> tuple[tuple[str, str], ...]:
    directory = Path(root)
    result = []
    for bank in _BANKS:
        path = directory / bank / f'{bank}_reference.png'
        if not path.is_file():
            logger.warning('OCR reference format missing: %s', path)
            return ()
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format='JPEG', quality=88, optimize=True)
            result.append((bank, base64.b64encode(output.getvalue()).decode('ascii')))
        except Exception:
            logger.warning('Unable to load OCR reference format: %s', path, exc_info=True)
            return ()
    return tuple(result)


def get_reference_formats() -> list[tuple[str, str]]:
    """Return ordered (bank code, base64 JPEG) references, or empty if incomplete."""
    return list(_load_references(str(_root().resolve())))


@lru_cache(maxsize=8)
def _negative_hashes(root: str) -> frozenset[str]:
    directory = Path(root) / 'negative_samples'
    if not directory.is_dir():
        logger.warning('OCR negative samples directory missing: %s', directory)
        return frozenset()
    return frozenset(hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in directory.iterdir() if path.is_file())


def is_known_negative(image_bytes: bytes) -> bool:
    return hashlib.sha256(image_bytes).hexdigest() in _negative_hashes(str(_root().resolve()))


def clear_reference_cache() -> None:
    """Clear caches for tests or runtime configuration changes."""
    _load_references.cache_clear()
    _negative_hashes.cache_clear()
