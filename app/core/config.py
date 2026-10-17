from pathlib import Path
from typing import Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General Settings
    PROJECT_NAME: str = "Student Marketplace C2C Backend"
    API_V1_STR: str = "/api/v1"
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v_str = v.strip()
            if v_str.startswith("[") and v_str.endswith("]"):
                try:
                    import json
                    parsed = json.loads(v_str)
                    if isinstance(parsed, list):
                        return [str(i).strip() for i in parsed if str(i).strip()]
                except Exception:
                    pass
            return [i.strip() for i in v_str.split(",") if i.strip()]
        return v
    
    # PostgreSQL
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "student_marketplace"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: Optional[str] = None

    # Redis
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    CLOUDINARY_ROOT_FOLDER: str = "student-marketplace"

    # Orders, Auctions & Worker
    ORDER_CONFIRM_TIMEOUT_HOURS: int = 24
    AUCTION_WINNER_CHECKOUT_HOURS: int = 24
    WORKER_POLL_INTERVAL_SECONDS: int = 30
    WORKER_BATCH_SIZE: int = 50
    WORKER_MAX_RETRIES: int = 3
    WORKER_RETRY_BACKOFF_SECONDS: float = 0.5

    # Product View Counter (Phase 9B)
    PRODUCT_VIEW_DEDUPE_SECONDS: int = 86400
    PRODUCT_VIEW_FLUSH_INTERVAL_SECONDS: int = 60
    PRODUCT_VIEW_FLUSH_BATCH_SIZE: int = 200

    # Rate Limiting & Abuse Prevention (Production Hardening)
    RATE_LIMIT_ENABLED: bool = True
    # Emergency volumetric flood ceiling (not primary scraper limit; sized for 100+ concurrent students on shared NAT)
    RATE_LIMIT_GLOBAL_IP_LIMIT: int = 3000
    RATE_LIMIT_GLOBAL_IP_WINDOW: int = 60
    RATE_LIMIT_PUBLIC_BROWSING_LIMIT: int = 120
    RATE_LIMIT_PUBLIC_BROWSING_WINDOW: int = 60
    RATE_LIMIT_USER_PROFILE_LIMIT: int = 60
    RATE_LIMIT_USER_PROFILE_WINDOW: int = 60
    RATE_LIMIT_USER_SEARCH_LIMIT: int = 30
    RATE_LIMIT_USER_SEARCH_WINDOW: int = 60
    RATE_LIMIT_WRITE_MUTATION_LIMIT: int = 30
    RATE_LIMIT_WRITE_MUTATION_WINDOW: int = 60
    RATE_LIMIT_CHAT_MESSAGE_LIMIT: int = 60
    RATE_LIMIT_CHAT_MESSAGE_WINDOW: int = 60
    RATE_LIMIT_AUTH_SENSITIVE_LIMIT: int = 20
    RATE_LIMIT_AUTH_SENSITIVE_WINDOW: int = 60

    # Chat Video Anti-Spam (Feature C)
    CHAT_VIDEO_UPLOAD_LIMIT: int = 5
    CHAT_VIDEO_UPLOAD_WINDOW_SECONDS: int = 600
    CHAT_MAX_VIDEOS_PER_MESSAGE: int = 1

    # Firebase
    FIREBASE_CREDENTIALS_PATH: Optional[str] = None
    FIREBASE_CREDENTIALS_JSON: Optional[str] = None

    # Community & Feedback Creator (stable server-side identity, not environment-local user_id)
    COMMUNITY_CREATOR_PROVIDER_UID: Optional[str] = None
    COMMUNITY_CREATOR_EMAIL: Optional[str] = None

    # Official Support Group (stable conversation_id for official support GROUP)
    OFFICIAL_SUPPORT_GROUP_ID: Optional[int] = None

    @property
    def database_url_async(self) -> str:
        if self.DATABASE_URL:
            if self.DATABASE_URL.startswith("postgresql://"):
                return self.DATABASE_URL.replace(
                    "postgresql://",
                    "postgresql+asyncpg://",
                    1,
                )
            return self.DATABASE_URL

        return (
            f"postgresql+asyncpg://"
            f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}"
            f"/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        if self.DATABASE_URL:
            if self.DATABASE_URL.startswith("postgresql+asyncpg://"):
                return self.DATABASE_URL.replace(
                    "postgresql+asyncpg://",
                    "postgresql://",
                    1,
                )
            return self.DATABASE_URL

        return (
            f"postgresql://"
            f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}"
            f"/{self.POSTGRES_DB}"
        )


settings = Settings()