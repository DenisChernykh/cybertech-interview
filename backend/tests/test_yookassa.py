import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.integrations.payments.base import ProviderUncertain
from app.integrations.payments.yookassa import YooKassaProvider


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setattr(settings(), "yookassa_shop_id", "test-shop")
    monkeypatch.setattr(settings(), "yookassa_secret_key", "test_fixture_not_a_real_key")


def response():
    return {
        "id": "remote-1",
        "status": "pending",
        "test": True,
        "recipient": {"account_id": "test-shop"},
    }


def test_create_sends_auth_capture_receipt_and_stable_key(config):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response())

    body = {
        "amount": {"value": "1190.00", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": "https://shop.example/orders/1"},
        "receipt": {"customer": {"email": "anna@example.com"}, "items": []},
    }
    with httpx.Client(
        base_url="https://api.yookassa.ru/v3/", transport=httpx.MockTransport(handle)
    ) as client:
        adapter = YooKassaProvider(client)
        adapter.create("payments", body, "same-key")
        adapter.create("payments", body, "same-key")
    assert calls[0].url.path == "/v3/payments"
    assert calls[0].headers["Authorization"].startswith("Basic ")
    assert calls[0].headers["Idempotence-Key"] == calls[1].headers["Idempotence-Key"] == "same-key"
    assert json.loads(calls[0].content) == body


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_uncertain_http_status_is_not_decline(config, status):
    with httpx.Client(
        base_url="https://api.yookassa.ru/v3/",
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"code": "error"})),
    ) as client:
        with pytest.raises(ProviderUncertain):
            YooKassaProvider(client).get("payments", "id")


def test_timeout_is_uncertain(config):
    def handle(request):
        raise httpx.ReadTimeout("timeout", request=request)

    with httpx.Client(
        base_url="https://api.yookassa.ru/v3/", transport=httpx.MockTransport(handle)
    ) as client:
        with pytest.raises(ProviderUncertain):
            YooKassaProvider(client).get("payments", "id")


def test_live_key_rejected_before_http():
    with pytest.raises(ValidationError):
        Settings(
            payment_provider="yookassa_test",
            yookassa_shop_id="shop",
            yookassa_secret_key="live_placeholder",
        )
    with pytest.raises(ValidationError):
        Settings(payment_provider="live")


def test_non_test_object_rejected(config):
    with httpx.Client(
        base_url="https://api.yookassa.ru/v3/",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={**response(), "test": False})
        ),
    ) as client:
        with pytest.raises(ProviderUncertain, match="non_test"):
            YooKassaProvider(client).get("payments", "remote")


def test_paginated_lists_and_cursor(config):
    requests = []

    def handle(request):
        requests.append(request)
        item = {**response(), "id": "second" if request.url.params.get("cursor") else "first"}
        return httpx.Response(
            200,
            json={
                "items": [item],
                **({} if request.url.params.get("cursor") else {"next_cursor": "page-2"}),
            },
        )

    with httpx.Client(
        base_url="https://api.yookassa.ru/v3/", transport=httpx.MockTransport(handle)
    ) as client:
        result = YooKassaProvider(client).list("payments", "2026-11-03T00:00:00Z")
    assert len(result) == 2
    assert requests[1].url.params["cursor"] == "page-2"
    assert requests[0].url.params["created_at.gte"] == "2026-11-03T00:00:00Z"


def test_refund_and_receipt_are_separate_requests(config):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "result", "status": "pending"})

    with httpx.Client(
        base_url="https://api.yookassa.ru/v3/", transport=httpx.MockTransport(handle)
    ) as client:
        adapter = YooKassaProvider(client)
        adapter.create(
            "refunds",
            {"payment_id": "pay", "amount": {"value": "1190.00", "currency": "RUB"}},
            "refund-key",
        )
        adapter.create(
            "receipts",
            {
                "type": "payment",
                "payment_id": "pay",
                "settlements": [
                    {"type": "prepayment", "amount": {"value": "1190.00", "currency": "RUB"}}
                ],
            },
            "receipt-key",
        )
    assert "receipt" not in json.loads(
        requests[0].content
    )  # Full refund receipt is automatic in selected scheme.
    assert requests[1].url.path == "/v3/receipts"
