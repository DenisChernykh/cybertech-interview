import copy
from decimal import Decimal

from sqlalchemy import select, text

from app.core.db import SessionLocal
from app.integrations.payments.base import ProviderRejected
from app.models.payments import MockObject
from app.models.store import now, uid


class MockPaymentProvider:
    # Provider ledger uses separate committed transactions, never changes shop orders.
    def create(self, kind, data, key):
        with SessionLocal.begin() as db:
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": "mock:" + kind + key},
            )
            old = db.scalar(
                select(MockObject).where(MockObject.kind == kind, MockObject.idempotency_key == key)
            )
            if old:
                if old.request != data:
                    raise ProviderRejected("idempotency_payload_mismatch")
                return copy.deepcopy(old.data)
            object_id = uid()
            result = {"id": object_id, "created_at": now().isoformat(), "test": True}
            if kind == "payments":
                result.update(
                    status="pending",
                    paid=False,
                    amount=data["amount"],
                    metadata=data["metadata"],
                    recipient={"account_id": "mock-shop"},
                    refunded_amount={"value": "0.00", "currency": "RUB"},
                    confirmation={"confirmation_url": "/demo/payments/" + object_id},
                    receipt_registration="pending",
                )
            elif kind == "refunds":
                payment = db.get(MockObject, data["payment_id"], with_for_update=True)
                if not payment or payment.data["status"] != "succeeded":
                    raise ProviderRejected("payment_not_succeeded")
                result.update(
                    status="pending",
                    amount=data["amount"],
                    payment_id=data["payment_id"],
                    receipt_registration="pending",
                )
            elif kind == "receipts":
                result.update(status="succeeded", type=data["type"], payment_id=data["payment_id"])
            else:
                raise ProviderRejected("unknown_object")
            db.add(
                MockObject(id=object_id, kind=kind, idempotency_key=key, request=data, data=result)
            )
            return copy.deepcopy(result)

    def get(self, kind, object_id):
        with SessionLocal() as db:
            item = db.get(MockObject, object_id)
            if not item or item.kind != kind:
                raise ProviderRejected("not_found")
            return copy.deepcopy(item.data)

    def list(self, kind, since):
        with SessionLocal() as db:
            return [
                copy.deepcopy(o.data)
                for o in db.scalars(
                    select(MockObject)
                    .where(MockObject.kind == kind)
                    .order_by(MockObject.created_at)
                )
            ]

    def decide(self, object_id, result, receipt_status="succeeded"):
        with SessionLocal.begin() as db:
            item = db.get(MockObject, object_id, with_for_update=True)
            if not item:
                raise ProviderRejected("not_found")
            data = copy.deepcopy(item.data)
            if data["status"] != "pending":
                return data
            if item.kind == "payments":
                data.update(
                    status=result, paid=result == "succeeded", receipt_registration=receipt_status
                )
                if result == "succeeded":
                    data["captured_at"] = now().isoformat()
                else:
                    data["cancellation_details"] = {
                        "party": "payment_network",
                        "reason": "insufficient_funds",
                    }
            elif item.kind == "refunds":
                payment = db.get(MockObject, data["payment_id"], with_for_update=True)
                paid = copy.deepcopy(payment.data)
                already = Decimal(paid["refunded_amount"]["value"])
                if result == "succeeded" and already + Decimal(data["amount"]["value"]) > Decimal(
                    paid["amount"]["value"]
                ):
                    result = "canceled"
                data.update(status=result, receipt_registration=receipt_status)
                if result == "succeeded":
                    paid["refunded_amount"] = {
                        "value": format(already + Decimal(data["amount"]["value"]), ".2f"),
                        "currency": "RUB",
                    }
                    payment.data = paid
                else:
                    data["cancellation_details"] = {
                        "party": "yoo_money",
                        "reason": "insufficient_funds",
                    }
            item.data = data
            return data

    def set_receipt(self, object_id, status):
        with SessionLocal.begin() as db:
            item = db.get(MockObject, object_id, with_for_update=True)
            data = copy.deepcopy(item.data)
            data["status" if item.kind == "receipts" else "receipt_registration"] = status
            item.data = data
