"""Independent settings for internal FDR analysis services.

These settings deliberately use their own prefix and never alias OCR or
Command Center credentials. Provider secrets remain backend-only.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntelligenceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='INTELLIGENCE_',
        env_file=Path(__file__).resolve().parents[2] / '.env',
        extra='ignore',
    )

    enabled: bool = False
    primary_artifact_path: str = './var/intelligence/active'
    artifact_path: str = './var/intelligence/artifacts'
    artifact_storage_prefix: str = 'private-intelligence-artifacts'
    training_max_rows: int = 100_000
    training_job_stale_minutes: int = 360
    inference_timeout_seconds: float = 3.0
    total_timeout_seconds: float = 20.0
    fallback_enabled: bool = False
    fallback_base_url: str = ''
    fallback_model: str = ''
    fallback_api_key: str = ''
    fallback_timeout_seconds: float = 10.0
    fallback_max_retries: int = 0

    @model_validator(mode='after')
    def validate_limits(self):
        if not 1 <= self.training_max_rows <= 1_000_000:
            raise ValueError('INTELLIGENCE_TRAINING_MAX_ROWS must be between 1 and 1000000.')
        if not 5 <= self.training_job_stale_minutes <= 1440:
            raise ValueError('INTELLIGENCE_TRAINING_JOB_STALE_MINUTES must be between 5 and 1440.')
        if not 0.1 <= self.inference_timeout_seconds <= 60:
            raise ValueError('INTELLIGENCE_INFERENCE_TIMEOUT_SECONDS must be between 0.1 and 60.')
        if not 1 <= self.total_timeout_seconds <= 120:
            raise ValueError('INTELLIGENCE_TOTAL_TIMEOUT_SECONDS must be between 1 and 120.')
        if not 0.1 <= self.fallback_timeout_seconds <= 60:
            raise ValueError('INTELLIGENCE_FALLBACK_TIMEOUT_SECONDS must be between 0.1 and 60.')
        if not 0 <= self.fallback_max_retries <= 2:
            raise ValueError('INTELLIGENCE_FALLBACK_MAX_RETRIES must be between 0 and 2.')
        if self.fallback_enabled and (not self.fallback_base_url.strip() or not self.fallback_model.strip()):
            raise ValueError('Enabled intelligence fallback requires its own endpoint and model.')
        return self


@lru_cache
def get_intelligence_settings() -> IntelligenceSettings:
    return IntelligenceSettings()
