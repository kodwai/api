from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    TURSO_DATABASE_URL: str
    TURSO_AUTH_TOKEN: str

    # JWT
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7

    # Encryption (hex-encoded 32-byte key for AES-256-GCM)
    ENCRYPTION_KEY: str

    # Resend
    RESEND_API_KEY: str = ""

    # Scoring
    SCORING_MODEL: str = "claude-sonnet-4-6"

    # GitHub OAuth
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    # URLs
    APP_URL: str = "http://localhost:8000"
    CLIENT_URL: str = "http://localhost:3000"
    LANDING_URL: str = "https://kodwai.com"

    # Vercel Blob
    BLOB_READ_WRITE_TOKEN: str = ""

    # Google Indexing
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""

    # Sentry
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    model_config = {"env_file": (".env", ".env.local"), "env_file_encoding": "utf-8"}


settings = Settings()  # type: ignore[call-arg]
