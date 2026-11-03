import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.store import owned
from app.core.auth import guest, manager
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import BusinessError
from app.integrations.payments.mock import MockPaymentProvider
from app.models import Reservation
from app.models.payments import Issue, Payment, Receipt, ReconciliationRun, Refund, RefundAttempt
from app.models.store import now
from app.repositories.store import get_order
from app.schemas import Reason
from app.services import payments as business
from app.services import store
from app.services.processing import accept_webhook

router = APIRouter(prefix="/api")


@router.post("/orders/{order_id}/payments", status_code=202)
def pay(order_id: str, identity=Depends(guest), db: Session = Depends(get_db)):
    order = owned(db, order_id, identity, True)
    business.prepare_payment(db, order)
    db.commit()
    return store.order_view(db, order)


@router.post("/manager/orders/{order_id}/refunds", status_code=202)
def refund(
    order_id: str, payload: Reason, identity=Depends(manager), db: Session = Depends(get_db)
):
    order = get_order(db, order_id, True)
    if not order.accepted_payment_id:
        raise BusinessError("not_paid", "Нет подтверждённой оплаты")
    payment = db.get(Payment, order.accepted_payment_id)
    result = business.request_refund(db, order, payment, payload.reason, "manager")
    if order.status != "canceled":
        store.cancel(db, order, payload.reason, "manager")
    db.commit()
    return {"refund_id": result.id, "status": result.status}


@router.post("/manager/refunds/{refund_id}/retry", status_code=202)
def retry(refund_id: str, identity=Depends(manager), db: Session = Depends(get_db)):
    refund = db.get(Refund, refund_id)
    if not refund:
        raise BusinessError("not_found", "Возврат не найден", 404)
    business.retry_refund(db, refund)
    db.commit()
    return {"status": refund.status}


@router.post("/manager/orders/{order_id}/reconcile", status_code=202)
def recheck(order_id: str, identity=Depends(manager), db: Session = Depends(get_db)):
    get_order(db, order_id)
    db.execute(update(Payment).where(Payment.order_id == order_id).values(next_check_at=now()))
    ids = select(Refund.id).where(Refund.order_id == order_id)
    db.execute(
        update(RefundAttempt).where(RefundAttempt.refund_id.in_(ids)).values(next_check_at=now())
    )
    db.execute(update(Receipt).where(Receipt.order_id == order_id).values(next_check_at=now()))
    db.commit()
    return {"status": "scheduled"}


@router.get("/manager/issues")
def problems(identity=Depends(manager), db: Session = Depends(get_db)):
    run = db.scalar(select(ReconciliationRun).order_by(ReconciliationRun.id.desc()))
    return {
        "issues": [
            {
                "id": i.id,
                "order_id": i.order_id,
                "code": i.code,
                "message": i.message,
                "created_at": i.created_at.isoformat(),
            }
            for i in db.scalars(select(Issue).where(~Issue.resolved).order_by(Issue.created_at))
        ],
        "reconciliation": None
        if not run
        else {
            "status": run.status,
            "at": run.started_at.isoformat(),
            "checked": run.checked,
            "stale": run.started_at
            < now() - timedelta(seconds=settings().reconciliation_seconds * 3),
        },
    }


@router.post("/webhooks/yookassa")
async def webhook(request: Request, db: Session = Depends(get_db)):
    if settings().payment_provider != "yookassa_test":
        raise BusinessError("disabled", "Webhook ЮKassa не включён", 404)
    if len(await request.body()) > 65536:
        raise BusinessError("too_large", "Слишком большое уведомление", 413)
    try:
        data = await request.json()
        event = data["event"]
        object_id = data["object"]["id"]
        if (
            data.get("type") != "notification"
            or event
            not in (
                "payment.succeeded",
                "payment.canceled",
                "payment.waiting_for_capture",
                "refund.succeeded",
            )
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", object_id)
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise BusinessError("bad_notification", "Некорректное уведомление", 400) from None
    accept_webhook(db, "yookassa_test", event, object_id)
    db.commit()
    return {"received": True}


class MockDecision(BaseModel):
    outcome: str
    notify: bool = True
    receipt_status: str = "succeeded"


def require_mock():
    if settings().payment_provider != "mock":
        raise BusinessError("disabled", "Демонстрационные действия выключены", 404)


@router.get("/demo/payments/{external_id}")
def mock_payment(external_id: str, identity=Depends(guest), db: Session = Depends(get_db)):
    require_mock()
    payment = db.scalar(
        select(Payment).where(Payment.provider == "mock", Payment.provider_id == external_id)
    )
    if not payment:
        raise BusinessError("not_found", "Платёж не найден", 404)
    order = owned(db, payment.order_id, identity)
    return {
        "id": external_id,
        "order_id": order.id,
        "number": order.number,
        "amount": store.money(payment.amount),
        "provider_status": MockPaymentProvider().get("payments", external_id)["status"],
    }


@router.post("/demo/payments/{external_id}")
def mock_decide(
    external_id: str, payload: MockDecision, identity=Depends(guest), db: Session = Depends(get_db)
):
    require_mock()
    payment = db.scalar(
        select(Payment).where(Payment.provider == "mock", Payment.provider_id == external_id)
    )
    if not payment:
        raise BusinessError("not_found", "Платёж не найден", 404)
    owned(db, payment.order_id, identity)
    if payload.outcome not in ("succeeded", "canceled") or payload.receipt_status not in (
        "succeeded",
        "pending",
        "canceled",
    ):
        raise BusinessError("invalid", "Неизвестный сценарий", 422)
    raw = MockPaymentProvider().decide(external_id, payload.outcome, payload.receipt_status)
    if payload.notify:
        accept_webhook(db, "mock", "payment." + raw["status"], external_id)
        db.commit()
    return {"status": raw["status"], "order_id": payment.order_id}


@router.post("/manager/demo/refunds/{attempt_id}")
def mock_refund(
    attempt_id: str, payload: MockDecision, identity=Depends(manager), db: Session = Depends(get_db)
):
    require_mock()
    attempt = db.get(RefundAttempt, attempt_id)
    if not attempt or not attempt.provider_id or attempt.provider != "mock":
        raise BusinessError("not_ready", "Дождитесь создания возврата")
    if payload.outcome not in ("succeeded", "canceled"):
        raise BusinessError("invalid", "Неизвестный сценарий", 422)
    raw = MockPaymentProvider().decide(attempt.provider_id, payload.outcome, payload.receipt_status)
    if payload.notify and raw["status"] == "succeeded":
        accept_webhook(db, "mock", "refund.succeeded", attempt.provider_id)
        db.commit()
    return {"status": raw["status"]}


@router.post("/manager/demo/orders/{order_id}/expire")
def expire(order_id: str, identity=Depends(manager), db: Session = Depends(get_db)):
    require_mock()
    get_order(db, order_id, True)
    reservation = db.get(Reservation, order_id)
    if reservation.status != "held":
        raise BusinessError("not_held", "Истекать может только неоплаченный резерв")
    reservation.expires_at = now() - timedelta(seconds=1)
    db.commit()
    return {"status": "scheduled"}


@router.post("/manager/demo/receipts/{receipt_id}")
def mock_receipt(
    receipt_id: str, payload: MockDecision, identity=Depends(manager), db: Session = Depends(get_db)
):
    require_mock()
    receipt = db.get(Receipt, receipt_id)
    if not receipt or payload.outcome not in ("succeeded", "pending", "canceled"):
        raise BusinessError("invalid", "Неизвестный чек или результат", 422)
    payment = db.get(Payment, receipt.payment_id)
    external_id = receipt.provider_id if receipt.kind == "final" else payment.provider_id
    if receipt.kind == "refund":
        attempt = db.scalar(
            select(RefundAttempt).where(
                RefundAttempt.refund_id == receipt.refund_id,
                RefundAttempt.provider_status == "succeeded",
            )
        )
        external_id = attempt.provider_id if attempt else None
    if not external_id:
        raise BusinessError("not_ready", "Внешняя операция ещё не создана")
    MockPaymentProvider().set_receipt(external_id, payload.outcome)
    receipt.next_check_at = now()
    db.commit()
    return {"status": "scheduled"}
