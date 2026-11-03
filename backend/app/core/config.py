from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    database_url: str = "postgresql+psycopg://shop:local-demo-only@localhost:55439/shop"
    manager_password: str = ""
    public_url: str = "http://localhost:8080"
    trusted_origins: str = "http://localhost:8080,http://localhost:5173"
    cookie_secure: bool = False
    reservation_minutes: int = 30
    smtp_host: str = "localhost"
    smtp_port: int = 1026


@lru_cache
def settings():
    return Settings()
