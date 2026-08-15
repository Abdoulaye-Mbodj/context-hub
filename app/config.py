from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Context Hub"
    app_public_url: str = "http://localhost:8080"
    database_url: str = "sqlite:///./context_hub.db"
    demo_mode: bool = True
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:8080"]
    integration_api_key: str = ""
    odoo_webhook_secret: str = ""
    app_secret_key: str = "local-development-key-change-me"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
