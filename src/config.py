from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")

    database_url: str
    anthropic_api_key: str
    google_credentials_path: Path = PROJECT_ROOT / "credentials.json"
    google_token_path: Path = PROJECT_ROOT / "token.json"
    data_dir: Path = PROJECT_ROOT / "data"
    log_level: str = "INFO"


settings = Settings()
