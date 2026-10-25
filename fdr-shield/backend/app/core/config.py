from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from cryptography.fernet import Fernet
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_env: str = 'dev'
    database_url: str = 'postgresql+asyncpg://fdr:fdr@localhost:5432/fdrshield'
    redis_url: str = 'redis://localhost:6379/0'
    jwt_secret: str = 'development-only-change-me'
    jwt_algorithm: str = 'HS256'
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    cookie_samesite: str = 'lax'
    cookie_domain: str = ''
    login_max_failures: int = 5
    lockout_minutes: int = 15
    initial_admin_email: str = ''
    initial_admin_password: str = ''
    mfa_encryption_key: str = ''
    frontend_origin: str = 'http://localhost:5173'
    s3_endpoint: str = 'http://localhost:9000'
    s3_access_key: str = 'minioadmin'
    s3_secret_key: str = 'minioadmin'
    s3_bucket: str = 'fdr-documents'
    mock_bank_url: str = 'http://localhost:9100'
    smtp_host: str = 'localhost'
    smtp_port: int = 1025
    telegram_bot_token: str = ''
    ocr_engine: str = 'ollama_vision'
    ollama_base_url: str = 'http://host.docker.internal:11434'
    ollama_model: str = 'gemma4:cloud'
    ollama_api_key: str = ''
    ollama_timeout: float = 120
    storage_backend: str = 'minio'
    storage_local_path: str = './var/fdr-documents'
    celery_task_always_eager: bool = False
    cors_origins: str = 'http://localhost:5173'
    trusted_proxy_ips: str = ''
    command_llm_enabled: bool = False
    command_llm_api_url: str = ''
    command_llm_api_key: str = ''
    command_llm_model: str = ''
    command_llm_timeout: float = 20
    clamav_host: str = ''
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 3
    rate_limit_commands_per_minute: int = 20
    rate_limit_assistant_per_minute: int = 20
    rate_limit_ocr_per_minute: int = 10
    rules_default_tz: str = 'Asia/Kolkata'

    @model_validator(mode='after')
    def validate_production_secrets(self):
        try: ZoneInfo(self.rules_default_tz)
        except ZoneInfoNotFoundError as exc: raise ValueError('RULES_DEFAULT_TZ must be a valid IANA timezone.') from exc
        if self.app_env.lower() not in {'dev', 'development', 'test'}:
            if len(self.jwt_secret) < 32 or self.jwt_secret == 'development-only-change-me':
                raise ValueError('JWT_SECRET must be a unique secret of at least 32 characters outside development.')
            if not self.cookie_secure:
                raise ValueError('COOKIE_SECURE must be enabled outside development.')
            if not self.frontend_origin.startswith('https://'):
                raise ValueError('FRONTEND_ORIGIN must use HTTPS outside development.')
            origins = [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]
            if '*' in origins or self.frontend_origin not in origins or any(not origin.startswith('https://') for origin in origins):
                raise ValueError('CORS_ORIGINS must list explicit HTTPS origins including FRONTEND_ORIGIN.')
            if not self.mfa_encryption_key:
                raise ValueError('MFA_ENCRYPTION_KEY must be configured outside development.')
            try: Fernet(self.mfa_encryption_key.encode())
            except Exception as exc: raise ValueError('MFA_ENCRYPTION_KEY must be a valid Fernet key.') from exc
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()
