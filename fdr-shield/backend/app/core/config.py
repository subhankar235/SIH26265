from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_env: str = 'dev'
    database_url: str = 'postgresql+asyncpg://fdr:fdr@localhost:5432/fdrshield'
    redis_url: str = 'redis://localhost:6379/0'
    jwt_secret: str = 'development-only-change-me'
    jwt_algorithm: str = 'HS256'
    access_token_minutes: int = 30
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

@lru_cache
def get_settings() -> Settings:
    return Settings()
