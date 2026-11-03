import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://shop:local-demo-only@localhost:55439/shop_test"
)
os.environ["MANAGER_PASSWORD"] = "test-manager-pass"
os.environ["TRUSTED_ORIGINS"] = "http://testserver,http://localhost:5173,http://localhost:8080"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.main import app
from app.models import Base
from app.seed import main as seed


@pytest.fixture(autouse=True)
def database():
    assert engine.url.database.endswith("_test"), "Tests require a dedicated *_test database"
    with engine.begin() as conn:
        tables = ", ".join('"' + t.name + '"' for t in Base.metadata.sorted_tables)
        conn.execute(text("TRUNCATE " + tables + " RESTART IDENTITY CASCADE"))
        conn.execute(text("ALTER SEQUENCE order_numbers RESTART WITH 1001"))
    seed()


@pytest.fixture
def client():
    with TestClient(app, headers={"origin": "http://testserver"}) as c:
        c.post("/api/session", json={})
        yield c


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def payload(client, product_id=1, quantity=1):
    import uuid

    basket = {"items": [{"product_id": product_id, "quantity": quantity}]}
    quote = client.post("/api/checkout/quote", json=basket)
    assert quote.status_code == 200, quote.text
    return {
        **basket,
        "quote_hash": quote.json()["quote_hash"],
        "checkout_key": str(uuid.uuid4()),
        "customer_name": "Анна Тестовая",
        "email": "anna@example.com",
        "address": "Екатеринбург, Ленина 1",
    }
