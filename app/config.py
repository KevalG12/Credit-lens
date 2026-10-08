"""Settings read from environment variables at call time (easy to override in tests)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DISCLAIMER = (
    "Demo project built on synthetic data. This is not a real credit score "
    "and must not be used for lending decisions."
)


class Settings:
    def __init__(self) -> None:
        # A PostgreSQL URL (Neon etc.) wins; otherwise a local SQLite file.
        self.db_path = (os.getenv("CREDITLENS_DATABASE_URL") or os.getenv("DATABASE_URL")
                        or os.getenv("CREDITLENS_DB", str(BASE_DIR / "creditlens.db")))
        self.model_path = os.getenv("CREDITLENS_MODEL", str(BASE_DIR / "app" / "ml" / "model.json"))
        self.jwt_secret = os.getenv("CREDITLENS_JWT_SECRET", "dev-only-change-me")
        self.jwt_minutes = int(os.getenv("CREDITLENS_JWT_MINUTES", "10080"))
        origins = os.getenv("CREDITLENS_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
        self.cors_origins = [o.strip() for o in origins.split(",") if o.strip()]
        self.max_upload_bytes = int(os.getenv("CREDITLENS_MAX_UPLOAD", "2000000"))
        self.env = os.getenv("CREDITLENS_ENV", "development").lower()
        # Max login/register attempts per client IP per minute (0 disables).
        self.auth_rate_limit = int(os.getenv("CREDITLENS_AUTH_RATE", "10"))
        self.frontend_dir = os.getenv("CREDITLENS_FRONTEND", str(BASE_DIR / "frontend"))


def get_settings() -> Settings:
    return Settings()
