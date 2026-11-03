from typing import Protocol


class ProviderUncertain(Exception):
    """Transport/5xx: operation may have happened. Keep original idempotency key."""


class ProviderRejected(Exception):
    """Definitive rejection of request; no successful operation was created."""


class PaymentProvider(Protocol):
    def create(self, kind: str, data: dict, key: str) -> dict: ...
    def get(self, kind: str, object_id: str) -> dict: ...
    def list(self, kind: str, since: str) -> list[dict]: ...
