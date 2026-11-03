import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from conftest import payload
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.errors import BusinessError
from app.main import app
from app.models import Order, Product, Reservation
from app.models.store import now
from app.schemas import Checkout
from app.services import store


def test_snapshot_and_idempotent_checkout(client, db):
    data = payload(client)
    first = client.post("/api/orders", json=data)
    assert first.status_code == 201, first.text
    again = client.post("/api/orders", json=data)
    assert again.json()["id"] == first.json()["id"]
    p = db.get(Product, 1)
    assert p.reserved == 1
    p.price = Decimal(2000)
    db.commit()
    result = client.get("/api/orders/" + first.json()["id"]).json()
    assert result["items"][0]["price"] == "890.00"
    assert result["total"] == "1190.00"
    data["address"] = "Другой адрес 2"
    assert client.post("/api/orders", json=data).status_code == 409


def test_price_change_requires_confirmation(client, db):
    data = payload(client)
    db.get(Product, 1).price = Decimal(900)
    db.commit()
    response = client.post("/api/orders", json=data)
    assert response.status_code == 409
    assert response.json()["code"] == "price_changed"
    assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_concurrent_last_item(client, db):
    data = payload(client)
    db.get(Product, 1).stock = 1
    db.commit()
    barrier = Barrier(2)

    def buy():
        with SessionLocal() as session:
            barrier.wait()
            try:
                order = store.create_order(
                    session,
                    Checkout(**{**data, "checkout_key": str(uuid.uuid4())}),
                    str(uuid.uuid4()),
                )
                session.commit()
                return order.id
            except BusinessError as e:
                session.rollback()
                return e.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: buy(), range(2)))
    assert results.count("out_of_stock") == 1
    db.expire_all()
    assert db.get(Product, 1).reserved == 1


def test_cancel_releases_once_and_access(client, db):
    order = client.post("/api/orders", json=payload(client)).json()
    with TestClient(app, headers={"origin": "http://testserver"}) as other:
        other.post("/api/session", json={})
        assert other.get("/api/orders/" + order["id"]).status_code == 404
        assert other.get("/api/manager/orders").status_code == 401
    for _ in range(2):
        assert (
            client.post(
                "/api/orders/" + order["id"] + "/cancel", json={"reason": "Передумала покупать"}
            ).status_code
            == 200
        )
    assert db.get(Product, 1).reserved == 0


def test_manual_fulfillment_and_return_to_shelf(client, db):
    order = client.post("/api/orders", json=payload(client)).json()
    # Existing orders retain the pre-integration manager workflow.
    db.get(Order, order["id"]).payment_policy = "manual"
    db.commit()
    assert (
        client.post("/api/manager/login", json={"password": "test-manager-pass"}).status_code == 200
    )
    path = "/api/manager/orders/" + order["id"]
    assert client.post(path + "/start-packing", json={}).json()["status"] == "packing"
    assert (
        client.post("/api/orders/" + order["id"] + "/cancel", json={"reason": "Отмена"}).status_code
        == 409
    )
    assert client.post(path + "/cancel", json={"reason": "Отмена согласована"}).status_code == 200
    assert db.get(Product, 1).reserved == 1
    assert client.post(path + "/release-stock", json={}).status_code == 200
    db.expire_all()
    assert db.get(Product, 1).reserved == 0


def test_expiry_and_origin(client, db):
    order = client.post("/api/orders", json=payload(client)).json()
    db.get(Reservation, order["id"]).expires_at = now() - timedelta(seconds=1)
    db.commit()
    store.expire_reservations(db)
    db.commit()
    assert client.get("/api/orders/" + order["id"]).json()["status"] == "canceled"
    assert (
        client.post(
            "/api/session", json={}, headers={"origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
