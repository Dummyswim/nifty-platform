from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo-root .env regardless of cwd; a missing file is ignored (containers use real env)
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    postgres_user: str = "nifty"
    postgres_password: str = ""
    postgres_db: str = "nifty"
    database_url: str = "postgresql+psycopg://nifty:nifty@127.0.0.1:5432/nifty"
    redis_url: str = "redis://127.0.0.1:6379/0"
    app_password_hash: str = ""
    app_secret_key: str = ""
    app_origins: str = "http://127.0.0.1:8080,http://127.0.0.1:5173"
    market_data_provider: str = "csv_replay"
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_redirect_url: str = "http://127.0.0.1:8000/api/v1/kite/callback"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.app_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
