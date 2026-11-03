from urllib.parse import quote

import httpx

from app.core.config import settings
from app.integrations.payments.base import ProviderRejected, ProviderUncertain


class YooKassaProvider:
    """Direct official API v3 adapter. No live-key or custom-endpoint mode."""

    def __init__(self, client=None):
        config = settings()
        if not config.yookassa_shop_id or not config.yookassa_secret_key.startswith("test_"):
            raise ValueError("Only test_ credentials are allowed")
        self.shop_id = config.yookassa_shop_id
        self.secret = config.yookassa_secret_key
        self.client = client
        self.timeout = config.provider_timeout_seconds

    def _request(self, method, path, data=None, key=None, params=None):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Idempotence-Key"] = key
        kwargs = {
            "auth": (self.shop_id, self.secret),
            "headers": headers,
            "params": params,
            "timeout": self.timeout,
        }
        if data is not None:
            kwargs["json"] = data
        try:
            if self.client is not None:
                response = self.client.request(method, path, **kwargs)
            else:
                with httpx.Client(base_url="https://api.yookassa.ru/v3/") as client:
                    response = client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderUncertain(type(exc).__name__) from None
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderUncertain("http_" + str(response.status_code))
        if response.status_code >= 400:
            try:
                code = str(response.json().get("code", "request_rejected"))[:100]
            except ValueError:
                code = "request_rejected"
            raise ProviderRejected("not_found" if response.status_code == 404 else code)
        try:
            payload = response.json()
        except ValueError:
            raise ProviderUncertain("invalid_json") from None
        if not isinstance(payload, dict):
            raise ProviderUncertain("invalid_response")
        return payload

    def _verify(self, kind, raw):
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("id"), str)
            or not isinstance(raw.get("status"), str)
        ):
            raise ProviderUncertain("missing_object_fields")
        if kind == "payments":
            if raw.get("test") is not True:
                raise ProviderUncertain("non_test_payment_blocked")
            recipient = raw.get("recipient")
            if not isinstance(recipient, dict) or str(recipient.get("account_id")) != self.shop_id:
                raise ProviderUncertain("wrong_shop")
        return raw

    def create(self, kind, data, key):
        if kind not in ("payments", "refunds", "receipts"):
            raise ValueError("Unsupported object")
        if kind == "payments" and (
            data.get("capture") is not True
            or data.get("confirmation", {}).get("type") != "redirect"
        ):
            raise ValueError("Only one-stage redirect payments are supported")
        return self._verify(kind, self._request("POST", kind, data, key))

    def get(self, kind, object_id):
        if kind not in ("payments", "refunds", "receipts"):
            raise ValueError("Unsupported object")
        return self._verify(kind, self._request("GET", kind + "/" + quote(object_id, safe="")))

    def list(self, kind, since):
        if kind not in ("payments", "refunds"):
            raise ValueError("Unsupported list")
        items = []
        cursor = None
        seen = set()
        while True:
            params = {"created_at.gte": since, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            raw = self._request("GET", kind, params=params)
            page = raw.get("items")
            if not isinstance(page, list):
                raise ProviderUncertain("invalid_list")
            items.extend(self._verify(kind, item) for item in page)
            cursor = raw.get("next_cursor")
            if not cursor:
                return items
            if cursor in seen:
                raise ProviderUncertain("repeated_cursor")
            seen.add(cursor)
