from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    anthropic_api_key: str
    google_credentials_path: Path = Path("./credentials.json")
    google_token_path: Path = Path("./token.json")
    data_dir: Path = Path("./data")
    log_level: str = "INFO"


settings = Settings()
