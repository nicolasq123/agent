from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    mysql_stat_url: SecretStr | None = None
    mysql_config_url: SecretStr | None = None
    query_backend: Literal["mysql", "http"] = "mysql"
    http_query_url: str | None = None
    http_query_token: SecretStr | None = None
    http_query_stat_db: str = "db20"
    http_query_config_db: str = "db40"
    stat_timezone: str = "UTC"
    cli_timezone: str = "Asia/Shanghai"
    model_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    auto_query_mode: int = 0
    artifacts_dir: Path = Path("artifacts")
    fixture_dir: Path = Path("../fixtures/demo")

    @model_validator(mode="after")
    def require_real_model_key(self) -> Self:
        if self.model_mode == "deepseek" and self.deepseek_api_key is None:
            raise ValueError("DEEPSEEK_API_KEY is required when MODEL_MODE=deepseek")
        if (
            self.data_mode == "readonly_db"
            and self.query_backend == "mysql"
            and (self.mysql_stat_url is None or self.mysql_config_url is None)
        ):
            raise ValueError(
                "MYSQL_STAT_URL and MYSQL_CONFIG_URL are required when DATA_MODE=readonly_db"
            )
        if self.query_backend == "http":
            if not self.http_query_url or not self.http_query_token:
                raise ValueError("HTTP_QUERY_URL and HTTP_QUERY_TOKEN are required")
            url = urlsplit(self.http_query_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.fragment
            ):
                raise ValueError(
                    "HTTP_QUERY_URL must be an HTTP(S) endpoint without credentials or fragment"
                )
            token = self.http_query_token.get_secret_value()
            if (
                not token.strip()
                or not token.isascii()
                or any(ord(char) < 32 or ord(char) == 127 for char in token)
            ):
                raise ValueError("HTTP_QUERY_TOKEN must be non-empty printable ASCII")
            if not self.http_query_stat_db.strip() or not self.http_query_config_db.strip():
                raise ValueError("HTTP query database names must not be empty")
        for field_name, value in (
            ("STAT_TIMEZONE", self.stat_timezone),
            ("CLI_TIMEZONE", self.cli_timezone),
        ):
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as error:
                raise ValueError(f"{field_name} must be a valid IANA timezone") from error
        return self
