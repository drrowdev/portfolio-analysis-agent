from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_file = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_env_file), env_file_encoding="utf-8")

    DATABASE_URL: str = "sqlite+aiosqlite:///./portfolio_agent.db"
    ANTHROPIC_API_KEY: str = ""
    NEWS_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""
    NTFY_TOPIC: str = "portfolio-alerts"
    APP_SECRET: str = ""  # Password for cookie-based access gate

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


settings = Settings()
