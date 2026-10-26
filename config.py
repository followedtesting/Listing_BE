import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENV: str = "development"

    DATA_DIR: str = "./data"

    # SMTP Email Configuration
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    EMAIL_TO: str = ""

    # NeonDB PostgreSQL Configuration
    DATABASE_URL: str = ""

    # Resend Email Configuration (HTTPS Port 443)
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "onboarding@resend.dev"

    # Subprocess Sandbox Configuration
    SUBPROCESS_MEMORY_LIMIT_MB: int = 350
    SUBPROCESS_TIMEOUT_SECONDS: int = 90
    MAX_ADAPTER_RETRIES: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def data_path(self) -> Path:
        path = Path(self.DATA_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

settings = Settings()
