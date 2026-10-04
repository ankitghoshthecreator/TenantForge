from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://tenantforge:tenantforge_secret@localhost:5432/tenantforge"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production-use-at-least-32-chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # S3 / MinIO (archival)
    S3_ENDPOINT_URL: str = "http://localhost:9000"  # set to "" for real AWS
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "tenantforge-archival"
    S3_REGION: str = "us-east-1"

    # App
    ENVIRONMENT: str = "development"
    PROJECT_NAME: str = "TenantForge"
    VERSION: str = "0.1.0"


settings = Settings()
