from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from conftest import payload
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.integrations.payments.base import ProviderUncertain
from app.integrations.payments.mock import MockPaymentProvider
from app.models import OperationEvent, Order, Product, Reservation
from app.models.payments import (
    EmailMessage,
    Issue,
    MockObject,
    Payment,
    Receipt,
    Refund,
    RefundAttempt,
)
from app.models.store import now
from app.repositories.store import get_order
from app.services import payments as business
from app.services.processing import accept_webhook, process_operation, tick


def order_and_payment(client):
    order = client.post("/api/orders", json=payload(client)).json()
    result = client.post("/api/orders/" + order["id"] + "/payments", json={})
    assert result.status_code == 202, result.text
    tick(force=True, mail=False)
    return client.get("/api/orders/" + order["id"]).json()


def settle(client, receipt="succeeded", notify=True):
    order = order_and_payment(client)
    p = order["payments"][-1]
    result = client.post(
        "/api/demo/payments/" + p["provider_id"],
        json={"outcome": "succeeded", "notify": notify, "receipt_status": receipt},
    )
    assert result.status_code == 200, result.text
    tick(force=True, mail=False)
    return client.get("/api/orders/" + order["id"]).json()


def manager(client):
    assert (
        client.post("/api/manager/login", json={"password": "test-manager-pass"}).status_code == 200
    )


def test_two_clicks_and_concurrent_requests_create_one_payment(client, db):
    order = client.post("/api/orders", json=payload(client)).json()
    barrier = Barrier(2)

    def prepare():
        with SessionLocal.begin() as s:
            barrier.wait()
            return business.prepare_payment(s, get_order(s, order["id"], True)).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: prepare(), range(2)))
    assert ids[0] == ids[1]
    assert client.post("/api/orders/" + order["id"] + "/payments", json={}).status_code == 202
    tick(force=True, mail=False)
    assert db.scalar(select(func.count()).select_from(Payment)) == 1
    assert (
        db.scalar(select(func.count()).select_from(MockObject).where(MockObject.kind == "payments"))
        == 1
    )


def test_decline_then_new_attempt_does_not_extend_reserve(client, db):
    order = order_and_payment(client)
    until = order["reservation"]["expires_at"]
    first = order["payments"][0]
    client.post("/api/demo/payments/" + first["provider_id"], json={"outcome": "canceled"})
    tick(force=True, mail=False)
    assert client.post("/api/orders/" + order["id"] + "/payments", json={}).status_code == 202
    tick(force=True, mail=False)
    result = client.get("/api/orders/" + order["id"]).json()
    assert len(result["payments"]) == 2
    assert result["payments"][0]["status"] == "canceled"
    assert result["reservation"]["expires_at"] == until


def test_lost_webhook_and_closed_page_recovered_by_reconciliation(client, db):
    order = order_and_payment(client)
    p = order["payments"][0]
    MockPaymentProvider().decide(p["provider_id"], "succeeded")
    assert db.get(Payment, p["id"]).provider_status == "pending"
    # No browser request or webhook delivery is needed to recover.
    tick(force=True, mail=False)
    db.expire_all()
    assert db.get(Order, order["id"]).accepted_payment_id == p["id"]
    assert db.get(Reservation, order["id"]).status == "allocated"
    assert db.get(Product, 1).reserved == 1


def test_duplicate_and_stale_webhook_no_duplicate_effects(client, db):
    order = settle(client)
    p = order["payments"][0]
    with SessionLocal.begin() as s:
        for _ in range(3):
            accept_webhook(s, "mock", "payment.succeeded", p["provider_id"])
        accept_webhook(s, "mock", "payment.canceled", p["provider_id"])
    tick(force=True, mail=False)
    assert (
        db.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.action == "payment_succeeded")
        )
        == 1
    )
    assert (
        db.scalar(
            select(func.count()).select_from(EmailMessage).where(EmailMessage.key.like("paid:%"))
        )
        == 1
    )
    assert db.get(Payment, p["id"]).provider_status == "succeeded"


def test_timeout_after_provider_commit_reuses_key(client, db, monkeypatch):
    order = client.post("/api/orders", json=payload(client)).json()
    client.post("/api/orders/" + order["id"] + "/payments", json={})
    p = db.scalar(select(Payment))
    original = MockPaymentProvider.create

    def uncertain(self, kind, data, key):
        original(self, kind, data, key)
        raise ProviderUncertain("lost_response")

    monkeypatch.setattr(MockPaymentProvider, "create", uncertain)
    process_operation(Payment, p.id, True)
    db.expire_all()
    assert db.get(Payment, p.id).state == "unknown"
    assert not client.get("/api/orders/" + order["id"]).json()["actions"]["pay"]
    monkeypatch.setattr(MockPaymentProvider, "create", original)
    process_operation(Payment, p.id, True)
    db.expire_all()
    assert db.get(Payment, p.id).provider_id
    assert (
        db.scalar(select(func.count()).select_from(MockObject).where(MockObject.kind == "payments"))
        == 1
    )


def test_worker_crash_after_remote_create_is_recoverable(client, db, monkeypatch):
    order = client.post("/api/orders", json=payload(client)).json()
    client.post("/api/orders/" + order["id"] + "/payments", json={})
    p = db.scalar(select(Payment))
    original = business.apply_payment

    def crash(*args):
        raise RuntimeError("simulated process crash before local commit")

    monkeypatch.setattr(business, "apply_payment", crash)
    with pytest.raises(RuntimeError):
        process_operation(Payment, p.id, True)
    monkeypatch.setattr(business, "apply_payment", original)
    process_operation(Payment, p.id, True)
    db.expire_all()
    assert db.get(Payment, p.id).state == "known"
    assert db.scalar(select(func.count()).select_from(MockObject)) == 1


def test_late_payment_queues_refund_without_reviving_order(client, db):
    order = order_and_payment(client)
    client.post("/api/orders/" + order["id"] + "/cancel", json={"reason": "Передумала покупать"})
    MockPaymentProvider().decide(order["payments"][0]["provider_id"], "succeeded")
    tick(force=True, mail=False)
    assert db.get(Order, order["id"]).status == "canceled"
    assert db.get(Product, 1).reserved == 0
    assert db.scalar(select(func.count()).select_from(Refund)) == 1
    assert db.scalar(select(Refund)).actor == "system"
    assert db.get(Order, order["id"]).accepted_payment_id is None


def test_paid_customer_cancel_requires_manager_approval(client, db):
    order = settle(client)
    client.post("/api/orders/" + order["id"] + "/cancel", json={"reason": "Передумала покупать"})
    tick(force=True, mail=False)
    refund = db.scalar(select(Refund))
    assert refund.status == "approval_required"
    assert db.scalar(select(func.count()).select_from(RefundAttempt)) == 0
    manager(client)
    response = client.post(
        "/api/manager/orders/" + order["id"] + "/refunds", json={"reason": "Отмена подтверждена"}
    )
    assert response.status_code == 202, response.text
    tick(force=True, mail=False)
    db.expire_all()
    assert db.get(Refund, refund.id).status == "processing"


def test_refund_failure_retry_and_no_regression_from_old_attempt(client, db):
    order = settle(client)
    manager(client)
    path = "/api/manager/orders/" + order["id"] + "/refunds"
    first = client.post(path, json={"reason": "Отмена согласована"})
    assert first.status_code == 202, first.text
    assert (
        client.post(path, json={"reason": "Повторный клик"}).json()["refund_id"]
        == first.json()["refund_id"]
    )
    tick(force=True, mail=False)
    attempt = db.scalar(select(RefundAttempt))
    MockPaymentProvider().decide(attempt.provider_id, "canceled")
    tick(force=True, mail=False)
    db.expire_all()
    refund = db.scalar(select(Refund))
    assert refund.status == "needs_attention"
    assert db.get(Payment, order["payments"][0]["id"]).refunded_amount == 0
    retry = client.post("/api/manager/refunds/" + refund.id + "/retry", json={})
    assert retry.status_code == 202, retry.text
    tick(force=True, mail=False)
    db.expire_all()
    attempts = list(db.scalars(select(RefundAttempt).order_by(RefundAttempt.created_at)))
    assert attempts[0].idempotency_key != attempts[1].idempotency_key
    MockPaymentProvider().decide(attempts[1].provider_id, "succeeded")
    tick(force=True, mail=False)
    tick(force=True, mail=False)
    db.expire_all()
    assert db.get(Refund, refund.id).status == "succeeded"
    assert db.get(Payment, order["payments"][0]["id"]).refunded_amount == Decimal(order["total"])
    assert db.scalar(select(func.count()).select_from(Receipt).where(Receipt.kind == "refund")) == 1


def test_receipt_error_blocks_shipping_until_verified_recovery(client, db):
    order = settle(client, receipt="canceled")
    manager(client)
    path = "/api/manager/orders/" + order["id"]
    assert client.post(path + "/start-packing", json={}).status_code == 200
    assert client.post(path + "/ship", json={}).json()["code"] == "receipt_failed"
    MockPaymentProvider().set_receipt(order["payments"][0]["provider_id"], "succeeded")
    tick(force=True, mail=False)
    assert client.post(path + "/ship", json={}).status_code == 200
    assert client.post(path + "/complete", json={}).status_code == 200
    tick(force=True, mail=False)
    db.expire_all()
    assert db.get(Product, 1).stock == 19
    assert db.get(Product, 1).reserved == 0
    final = db.scalar(select(Receipt).where(Receipt.kind == "final"))
    assert final.status == "registered"
    assert final.request["settlements"][0]["type"] == "prepayment"


def test_mismatch_never_marks_paid(client, db):
    order = order_and_payment(client)
    p = order["payments"][0]
    raw = MockPaymentProvider().decide(p["provider_id"], "succeeded")
    raw["amount"] = {"value": "1.00", "currency": "RUB"}
    with SessionLocal.begin() as s:
        business.apply_payment(s, p["id"], raw)
    assert db.get(Order, order["id"]).accepted_payment_id is None
    assert db.scalar(select(Issue).where(Issue.code == "payment_mismatch"))


def test_paid_reserve_does_not_expire(client, db):
    order = settle(client)
    db.get(Reservation, order["id"]).expires_at = now() - timedelta(hours=1)
    db.commit()
    tick(force=True, mail=False)
    db.expire_all()
    assert db.get(Order, order["id"]).status == "placed"
    assert db.get(Reservation, order["id"]).status == "allocated"


def test_no_new_post_after_idempotency_window(client, db, monkeypatch):
    order = client.post("/api/orders", json=payload(client)).json()
    client.post("/api/orders/" + order["id"] + "/payments", json={})
    p = db.scalar(select(Payment))
    p.sent_at = now() - timedelta(hours=25)
    p.state = "unknown"
    db.commit()

    def forbidden(*args):
        pytest.fail("Must not create a new remote operation after 24h")

    monkeypatch.setattr(MockPaymentProvider, "create", forbidden)
    process_operation(Payment, p.id, True)
    db.expire_all()
    assert db.get(Payment, p.id).state == "blocked"
