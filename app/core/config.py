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
    # Resend webhook signing secret (whsec_...), verifies POST /api/webhooks/resend.
    RESEND_WEBHOOK_SECRET: str = ""

    # Email identities. Auth mail (verification, password reset, invites) keeps the
    # transactional sender. Lifecycle and feedback mail comes from the updates
    # subdomain with replies routed to the founder's inbox; real lifecycle and
    # feedback sends refuse while EMAIL_REPLY_TO is empty.
    EMAIL_FROM_TRANSACTIONAL: str = "Kodwai <noreply@kodwai.com>"
    EMAIL_FROM_LIFECYCLE: str = '"Hakan from Kodwai" <hi@updates.kodwai.com>'
    EMAIL_REPLY_TO: str = ""
    # HMAC key for stateless one-click unsubscribe tokens (List-Unsubscribe links).
    UNSUBSCRIBE_SECRET: str = ""
    # Postal address printed in lifecycle email footers (CAN-SPAM).
    COMPANY_POSTAL_ADDRESS: str = ""
    # Comma-separated emails excluded from lifecycle sends and growth stats
    # (founder, team and test accounts). Demo accounts are excluded separately.
    INTERNAL_EMAILS: str = ""
    # Starter challenge used in onboarding emails (the one /dev/welcome points at).
    LIFECYCLE_STARTER_CHALLENGE_SLUG: str = "bookshelf-rest-api"

    # Server-side PostHog capture. Empty key = capture is a no-op.
    POSTHOG_PROJECT_KEY: str = ""
    POSTHOG_HOST: str = "https://us.i.posthog.com"

    # IndexNow key. Public by design: the landing serves /<key>.txt containing exactly
    # this value, so it is safe as a default. Set to "" to turn IndexNow pings off.
    INDEXNOW_KEY: str = "b8769b2b667d49da7b546dde47009a36"

    # Scoring
    SCORING_MODEL: str = "claude-sonnet-4-6"

    # Free tier — developers get FREE_SUBMISSION_LIMIT challenge submissions
    # scored with the platform's own Anthropic key before they must add their
    # own. Leave PLATFORM_ANTHROPIC_API_KEY empty to disable the free tier
    # (developers then need their own key from the first submission).
    PLATFORM_ANTHROPIC_API_KEY: str = ""
    FREE_SUBMISSION_LIMIT: int = 3

    # GitHub OAuth
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    # URLs
    APP_URL: str = "http://localhost:8000"
    CLIENT_URL: str = "http://localhost:3000"
    LANDING_URL: str = "https://www.kodwai.com"
    # Public base URL of this API for links placed in outgoing email (List-Unsubscribe).
    # APP_URL is environment-specific, so it is not used for those links.
    PUBLIC_API_URL: str = "https://api.kodwai.com"

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

    @property
    def internal_emails_list(self) -> list[str]:
        """INTERNAL_EMAILS as a sorted, lowercased, de-duplicated list (safe for SQL IN params)."""
        return sorted({email.strip().lower() for email in self.INTERNAL_EMAILS.split(",") if email.strip()})

    model_config = {"env_file": (".env", ".env.local"), "env_file_encoding": "utf-8"}


settings = Settings()  # type: ignore[call-arg]
