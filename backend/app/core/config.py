from pydantic_settings import BaseSettings, SettingsConfigDict

# Shared analytics/config core (editable install, see root pyproject.toml) --
# reuse its non-secret constants rather than redefining them here.
import config.settings as shared_settings

PROJECT_ROOT = shared_settings.PROJECT_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"), extra="ignore")

    DATABASE_URL: str
    DB_SCHEMA: str = "public"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    @property
    def live_loop_interval_min(self) -> int:
        return shared_settings.LIVE_LOOP_INTERVAL_MIN

    @property
    def session_open(self) -> str:
        return shared_settings.SESSION_OPEN

    @property
    def session_close(self) -> str:
        return shared_settings.SESSION_CLOSE

    @property
    def ist(self):
        return shared_settings.IST


settings = Settings()
