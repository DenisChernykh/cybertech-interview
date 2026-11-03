from functools import lru_cache
from typing import Literal

from pydantic import model_validator
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
    payment_provider: Literal["mock", "yookassa_test"] = "mock"
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    receipt_vat_code: int = 1
    reconciliation_seconds: int = 60
    provider_timeout_seconds: float = 10

    @model_validator(mode="after")
    def test_only(self):
        if self.payment_provider == "yookassa_test":
            if not self.yookassa_shop_id or not self.yookassa_secret_key.startswith("test_"):
                raise ValueError("Only YooKassa test_ credentials are allowed")
        return self


@lru_cache
def settings():
    return Settings()
