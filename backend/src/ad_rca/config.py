from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_mode: Literal["fixture", "readonly_db"] = "fixture"
    model_mode: Literal["fake", "deepseek"] = "fake"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    model_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    artifacts_dir: Path = Path("artifacts")
    fixture_dir: Path = Path("../fixtures/demo")

    @model_validator(mode="after")
    def require_real_model_key(self) -> Self:
        if self.model_mode == "deepseek" and self.deepseek_api_key is None:
            raise ValueError("DEEPSEEK_API_KEY is required when MODEL_MODE=deepseek")
        return self

