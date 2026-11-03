"""Exercise a real API/worker stop with a committed mock payment and no webhook.

Run from the repository root, with Compose running in mock mode. This changes
only the list-shop API/worker containers and creates/refunds one demo order.
"""

import json
import os
import subprocess
import time
import uuid
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
URL = "http://localhost:8080"
client = build_opener(HTTPCookieProcessor(CookieJar()))


def api(path, body=None):
    request = Request(
        URL + "/api" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Origin": URL},
    )
    with client.open(request, timeout=10) as response:
        return json.load(response)


def until(read, ready, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = read()
            if ready(value):
                return value
        except (HTTPError, URLError, TimeoutError):
            pass
        time.sleep(1)
    raise AssertionError("Expected state was not reached within the timeout")


def compose(*args):
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True)


def main():
    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    password = os.environ.get("MANAGER_PASSWORD", env.get("MANAGER_PASSWORD", ""))
    assert password, "Manager password is required for cleanup"
    api("/session", {})
    product = next(p for p in api("/products") if p["available"])
    basket = {"items": [{"product_id": product["id"], "quantity": 1}]}
    quote = api("/checkout/quote", basket)
    order = api(
        "/orders",
        {
            **basket,
            "quote_hash": quote["quote_hash"],
            "checkout_key": str(uuid.uuid4()),
            "customer_name": "Проверка восстановления",
            "email": "outage@example.com",
            "address": "Екатеринбург, тестовый адрес 1",
        },
    )
    assert order["provider"] == "mock", "This scenario is allowed only with MockPaymentProvider"
    path = "/orders/" + order["id"]
    api(path + "/payments", {})
    order = until(lambda: api(path), lambda o: o["payments"][-1]["provider_id"])
    payment_id = order["payments"][-1]["provider_id"]
    print(f"Order {order['number']}: payment pending; stopping API and worker", flush=True)
    try:
        compose("stop", "api", "worker")
        try:
            api("/health")
        except (HTTPError, URLError, TimeoutError):
            print("API is unavailable, as expected", flush=True)
        else:
            raise AssertionError("API unexpectedly remained available")
        # Independent mock ledger commit: no API server, worker or webhook is running.
        compose(
            "run",
            "--rm",
            "--no-deps",
            "api",
            "python",
            "-c",
            "import sys; from app.integrations.payments.mock import MockPaymentProvider; "
            "MockPaymentProvider().decide(sys.argv[1], 'succeeded'); "
            "print('Provider ledger committed success without webhook')",
            payment_id,
        )
    finally:
        compose("start", "api", "worker")
    order = until(lambda: api(path), lambda o: o["accepted_payment_id"])
    assert order["status"] == "placed" and order["reservation"]["status"] == "allocated"
    print("Restart recovery: paid order and allocated stock restored", flush=True)
    api("/manager/login", {"password": password})
    manager_path = "/manager" + path
    history = api(manager_path)["history"]
    assert sum(e["action"] == "payment_succeeded" for e in history) == 1
    api(manager_path + "/refunds", {"reason": "Завершение проверки восстановления"})
    order = until(
        lambda: api(path),
        lambda o: (
            o["refunds"]
            and o["refunds"][-1]["attempts"]
            and o["refunds"][-1]["attempts"][-1]["provider_id"]
        ),
    )
    attempt = order["refunds"][-1]["attempts"][-1]
    api("/manager/demo/refunds/" + attempt["id"], {"outcome": "succeeded"})
    order = until(lambda: api(path), lambda o: o["refunds"][-1]["status"] == "succeeded")
    assert order["status"] == "canceled" and order["reservation"]["status"] == "released"
    print("PASS: recovered once, full mock refund confirmed, stock released", flush=True)


if __name__ == "__main__":
    main()
