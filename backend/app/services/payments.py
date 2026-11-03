from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.errors import BusinessError
from app.models import Reservation
from app.models.payments import EmailMessage, Issue, Payment, Receipt, Refund, RefundAttempt
from app.models.store import now, uid
from app.repositories.store import get_order, items
from app.services.store import event, money


def issue(db, key, code, message, order_id=None):
    db.execute(
        insert(Issue)
        .values(
            key=key,
            code=code,
            message=message,
            order_id=order_id,
            resolved=False,
            created_at=now(),
            updated_at=now(),
        )
        .on_conflict_do_update(
            index_elements=["key"],
            set_={"code": code, "message": message, "resolved": False, "updated_at": now()},
        )
    )


def resolve(db, key):
    db.execute(update(Issue).where(Issue.key == key).values(resolved=True, updated_at=now()))


def email(db, order, key, text):
    db.execute(
        insert(EmailMessage)
        .values(
            key=key,
            order_id=order.id,
            recipient=order.email,
            subject=f"Лист · заказ № {order.number}",
            body=text
            + f"\nЗаказ: {settings().public_url}/orders/{order.id}\nДемонстрация. Реальные списания не выполнялись.",
            status="queued",
            attempts=0,
            next_check_at=now(),
        )
        .on_conflict_do_nothing(index_elements=["key"])
    )


def receipt_data(db, order):
    lines = [
        {
            "description": i.name,
            "quantity": str(i.quantity),
            "amount": {"value": money(i.price - i.discount), "currency": "RUB"},
            "vat_code": i.vat_code,
            "payment_mode": "full_prepayment",
            "payment_subject": "commodity",
        }
        for i in items(db, order.id)
    ]
    if order.delivery:
        lines.append(
            {
                "description": "Доставка",
                "quantity": "1",
                "amount": {"value": money(order.delivery), "currency": "RUB"},
                "vat_code": settings().receipt_vat_code,
                "payment_mode": "full_prepayment",
                "payment_subject": "service",
            }
        )
    return {"customer": {"email": order.email}, "items": lines}


def prepare_payment(db, order):
    if order.payment_policy != "online" or order.status != "placed" or order.accepted_payment_id:
        raise BusinessError("cannot_pay", "Этот заказ нельзя оплатить")
    reservation = db.get(Reservation, order.id)
    if reservation.status != "held" or reservation.expires_at <= now():
        raise BusinessError("reservation_expired", "Срок резерва истёк. Оформите новый заказ")
    existing = db.scalar(select(Payment).where(Payment.order_id == order.id, Payment.active))
    if existing:
        return existing
    if db.scalar(select(Payment).where(Payment.order_id == order.id, Payment.state == "blocked")):
        raise BusinessError("payment_review", "Сначала менеджер должен проверить предыдущую оплату")
    payment = Payment(
        id=uid(), order_id=order.id, provider=settings().payment_provider, amount=order.total
    )
    payment.request = {
        "amount": {"value": money(order.total), "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": f"{settings().public_url}/orders/{order.id}",
        },
        "description": f"Заказ № {order.number}",
        "metadata": {"order_id": order.id, "attempt_id": payment.id},
        "receipt": receipt_data(db, order),
    }
    db.add(payment)
    db.flush()
    event(db, order, "payment_requested", "customer", attempt_id=payment.id)
    return payment


def ensure_receipt(db, order, payment, kind, raw_status=None, refund=None):
    key = kind + ":" + (refund.id if refund else payment.id)
    receipt = db.scalar(select(Receipt).where(Receipt.event_key == key))
    if not receipt:
        payload = deepcopy(payment.request["receipt"])
        if kind == "final":
            for line in payload["items"]:
                line["payment_mode"] = "full_payment"
            payload.update(
                type="payment",
                payment_id=payment.provider_id,
                send=True,
                settlements=[
                    {
                        "type": "prepayment",
                        "amount": {"value": money(payment.amount), "currency": "RUB"},
                    }
                ],
            )
        receipt = Receipt(
            event_key=key,
            order_id=order.id,
            payment_id=payment.id,
            refund_id=refund.id if refund else None,
            kind=kind,
            request=payload,
        )
        db.add(receipt)
        db.flush()
    if raw_status is not None:
        receipt.status = {
            "succeeded": "registered",
            "canceled": "failed",
            "pending": "pending",
        }.get(raw_status, "pending")
        receipt.last_checked_at = now()
        if receipt.status == "failed":
            receipt.last_error = "Регистрация отклонена кассовым сервисом"
            issue(
                db,
                "receipt:" + receipt.id,
                "receipt_failed",
                "Чек не зарегистрирован. Проверьте кассу и данные; не создавайте дубликат.",
                order.id,
            )
        elif receipt.status == "registered":
            receipt.last_error = None
            resolve(db, "receipt:" + receipt.id)
    return receipt


def request_refund(db, order, payment, reason, actor):
    existing = db.scalar(select(Refund).where(Refund.payment_id == payment.id))
    if existing:
        if existing.status == "approval_required" and actor == "manager":
            existing.status = "requested"
            db.add(
                RefundAttempt(
                    refund_id=existing.id,
                    provider=payment.provider,
                    request={
                        "payment_id": payment.provider_id,
                        "amount": {"value": money(existing.amount), "currency": "RUB"},
                        "description": existing.reason[:250],
                    },
                )
            )
            event(db, order, "refund_approved", actor, refund_id=existing.id)
        return existing
    if payment.provider_status != "succeeded" or not payment.provider_id:
        raise BusinessError("not_paid", "Нет подтверждённой оплаты")
    if payment.refunded_amount:
        raise BusinessError(
            "external_refund", "У провайдера уже есть возврат. Сначала выполните сверку"
        )
    if actor == "manager" and order.status not in ("placed", "packing", "canceled"):
        raise BusinessError(
            "already_shipped", "После отправки возврат требует отдельного согласования"
        )
    refund = Refund(
        id=uid(),
        order_id=order.id,
        payment_id=payment.id,
        amount=payment.amount,
        reason=reason,
        actor=actor,
    )
    db.add(refund)
    db.flush()
    if actor == "customer":
        refund.status = "approval_required"
        issue(
            db,
            "refund:" + refund.id,
            "refund_approval",
            "Покупатель отменил оплаченный заказ. Менеджеру нужно подтвердить полный возврат.",
            order.id,
        )
        event(db, order, "refund_approval_required", actor, refund_id=refund.id)
        return refund
    attempt = RefundAttempt(
        refund_id=refund.id,
        provider=payment.provider,
        request={
            "payment_id": payment.provider_id,
            "amount": {"value": money(payment.amount), "currency": "RUB"},
            "description": reason[:250],
        },
    )
    db.add(attempt)
    issue(
        db,
        "refund:" + refund.id,
        "refund_pending",
        "Деньги нужно вернуть. Ожидаем подтверждение возврата.",
        order.id,
    )
    event(
        db,
        order,
        "refund_requested",
        actor,
        refund_id=refund.id,
        amount=money(payment.amount),
        reason=reason,
    )
    email(
        db,
        order,
        "refund-requested:" + refund.id,
        "Заказ отменён. Возврат оплаты принят в обработку.",
    )
    return refund


def refund_after_cancel(db, order, actor="system"):
    if order.accepted_payment_id:
        payment = db.get(Payment, order.accepted_payment_id)
        request_refund(db, order, payment, order.cancel_reason or "Заказ отменён", actor)


def retry_refund(db, refund):
    order = get_order(db, refund.order_id, True)
    # The API may have read the refund before waiting for the order lock.
    db.refresh(refund)
    if refund.status != "needs_attention" or db.scalar(
        select(RefundAttempt).where(RefundAttempt.refund_id == refund.id, RefundAttempt.active)
    ):
        raise BusinessError(
            "cannot_retry", "Сначала нужно определить результат предыдущей операции"
        )
    previous = db.scalar(
        select(RefundAttempt)
        .where(RefundAttempt.refund_id == refund.id)
        .order_by(RefundAttempt.created_at.desc())
    )
    if previous.state == "blocked":
        raise BusinessError(
            "unknown_result", "Неизвестную операцию нельзя повторить новым запросом"
        )
    db.add(
        RefundAttempt(
            refund_id=refund.id, provider=previous.provider, request=deepcopy(previous.request)
        )
    )
    refund.status = "requested"
    event(db, order, "refund_retry", "manager", refund_id=refund.id)


def valid_payment(payment, raw):
    if raw.get("test") is not True:
        return "Получен объект вне тестового режима"
    if (
        raw.get("amount", {}).get("currency") != "RUB"
        or Decimal(str(raw.get("amount", {}).get("value", "-1"))) != payment.amount
    ):
        return "Сумма или валюта платежа не совпадает с заказом"
    if (
        raw.get("metadata", {}).get("order_id") != payment.order_id
        or raw.get("metadata", {}).get("attempt_id") != payment.id
    ):
        return "Не совпадает привязка платежа к заказу и попытке"
    expected = "mock-shop" if payment.provider == "mock" else settings().yookassa_shop_id
    if str(raw.get("recipient", {}).get("account_id")) != expected:
        return "Платёж принадлежит другому магазину"
    if payment.provider_id and raw.get("id") != payment.provider_id:
        return "Изменился идентификатор платежа"
    if raw.get("status") not in ("pending", "succeeded", "canceled"):
        return "Неожиданное состояние для одностадийного платежа"
    if raw.get("status") == "succeeded" and raw.get("paid") is not True:
        return "Успешный платёж не подтверждён признаком paid"
    if (
        payment.provider_status in ("succeeded", "canceled")
        and payment.provider_status != raw["status"]
    ):
        return "Попытка изменить окончательное состояние платежа"
    return None


def apply_payment(db, payment_id, raw):
    payment = db.get(Payment, payment_id)
    order = get_order(db, payment.order_id, True)
    error = valid_payment(payment, raw)
    if error:
        payment.state, payment.last_error = "blocked", error
        issue(
            db,
            "payment:" + payment.id,
            "payment_mismatch",
            error + ". Исполнение заблокировано.",
            order.id,
        )
        return
    old = payment.provider_status
    payment.provider_id = raw["id"]
    payment.provider_status = raw["status"]
    payment.state, payment.last_error, payment.last_checked_at = "known", None, now()
    payment.active = raw["status"] == "pending"
    payment.next_check_at = now() + timedelta(seconds=settings().reconciliation_seconds)
    refunded = Decimal(str(raw.get("refunded_amount", {}).get("value", "0")))
    if not refunded.is_finite() or refunded < 0 or refunded > payment.amount:
        payment.state = "blocked"
        issue(
            db,
            "payment:" + payment.id,
            "payment_mismatch",
            "Некорректная сумма возвратов",
            order.id,
        )
        return
    # A delayed payment snapshot must not undo an already confirmed refund.
    refunded = max(refunded, payment.refunded_amount)
    payment.refunded_amount = refunded
    url = raw.get("confirmation", {}).get("confirmation_url")
    if url:
        parsed = urlparse(url)
        if (payment.provider == "mock" and url.startswith("/demo/payments/")) or (
            payment.provider == "yookassa_test"
            and parsed.scheme == "https"
            and (parsed.hostname or "").split(".")[-2:] in (["yookassa", "ru"], ["yoomoney", "ru"])
        ):
            payment.confirmation_url = url
        else:
            payment.state = "blocked"
            issue(
                db,
                "payment:" + payment.id,
                "payment_mismatch",
                "Недопустимая ссылка оплаты",
                order.id,
            )
            return
    resolve(db, "payment:" + payment.id)
    resolve(db, "payments:" + payment.id)
    if raw["status"] == "succeeded":
        ensure_receipt(db, order, payment, "prepayment", raw.get("receipt_registration", "pending"))
        known_refund = db.scalar(
            select(Refund).where(Refund.payment_id == payment.id, Refund.status == "succeeded")
        )
        if refunded and not known_refund:
            issue(
                db,
                "external-refund:" + payment.id,
                "external_refund",
                "Обнаружен возврат у провайдера. Сверьте его с учётом магазина.",
                order.id,
            )
        elif known_refund:
            resolve(db, "external-refund:" + payment.id)
        if order.status == "canceled":
            if not refunded:
                request_refund(db, order, payment, "Оплата пришла после отмены заказа", "system")
        elif order.accepted_payment_id and order.accepted_payment_id != payment.id:
            request_refund(db, order, payment, "Дополнительная оплата одного заказа", "system")
        elif not order.accepted_payment_id and not refunded:
            order.accepted_payment_id = payment.id
            db.get(Reservation, order.id).status = "allocated"
            event(
                db,
                order,
                "payment_succeeded",
                "provider",
                amount=money(payment.amount),
                provider_id=payment.provider_id,
            )
            email(
                db,
                order,
                "paid:" + payment.id,
                f"Тестовая оплата {money(payment.amount)} ₽ подтверждена. Заказ готов к комплектации.",
            )
    elif raw["status"] == "canceled" and old != "canceled":
        payment.last_error = raw.get("cancellation_details", {}).get("reason", "payment_canceled")
        event(db, order, "payment_canceled", "provider", reason=payment.last_error)


def apply_refund(db, attempt_id, raw):
    attempt = db.get(RefundAttempt, attempt_id)
    refund = db.get(Refund, attempt.refund_id)
    order = get_order(db, refund.order_id, True)
    payment = db.get(Payment, refund.payment_id)
    if (
        raw.get("payment_id") != payment.provider_id
        or raw.get("amount", {}).get("currency") != "RUB"
        or Decimal(str(raw.get("amount", {}).get("value", "-1"))) != refund.amount
        or raw.get("status") not in ("pending", "succeeded", "canceled")
        or (attempt.provider_id and attempt.provider_id != raw.get("id"))
    ):
        attempt.state = "blocked"
        refund.status = "needs_attention"
        issue(
            db,
            "refund:" + refund.id,
            "refund_mismatch",
            "Ответ возврата не совпадает с операцией. Требуется сверка.",
            order.id,
        )
        return
    if (
        attempt.provider_status in ("succeeded", "canceled")
        and attempt.provider_status != raw["status"]
    ):
        issue(
            db,
            "refund:" + refund.id,
            "refund_mismatch",
            "Провайдер изменил окончательный статус возврата",
            order.id,
        )
        attempt.state = "blocked"
        return
    previous_status = attempt.provider_status
    attempt.provider_id, attempt.provider_status = raw["id"], raw["status"]
    attempt.state, attempt.last_checked_at = "known", now()
    attempt.next_check_at = now() + timedelta(seconds=settings().reconciliation_seconds)
    attempt.active = raw["status"] == "pending"
    resolve(db, "refunds:" + attempt.id)
    resolve(db, "unmatched-refund:" + attempt.provider + ":" + raw["id"])
    latest_id = db.scalar(
        select(RefundAttempt.id)
        .where(RefundAttempt.refund_id == refund.id)
        .order_by(RefundAttempt.created_at.desc())
        .limit(1)
    )
    if raw["status"] != "succeeded" and (refund.status == "succeeded" or latest_id != attempt.id):
        return
    if raw["status"] == "succeeded":
        if refund.status != "succeeded":
            event(db, order, "refund_succeeded", "provider", amount=money(refund.amount))
            email(
                db,
                order,
                "refunded:" + refund.id,
                "ЮKassa/Mock подтвердил выполнение возврата. Срок зачисления зависит от банка; в демонстрации настоящих денег нет.",
            )
        refund.status = "succeeded"
        payment.refunded_amount = refund.amount
        ensure_receipt(
            db, order, payment, "refund", raw.get("receipt_registration", "pending"), refund
        )
        resolve(db, "refund:" + refund.id)
        resolve(db, "external-refund:" + payment.id)
    elif raw["status"] == "canceled":
        refund.status = "needs_attention"
        attempt.last_error = raw.get("cancellation_details", {}).get("reason", "unknown")
        issue(
            db,
            "refund:" + refund.id,
            "refund_failed",
            "Возврат отклонён: " + attempt.last_error + ". Устраните причину перед повтором.",
            order.id,
        )
        if previous_status != "canceled":
            event(db, order, "refund_failed", "provider", reason=attempt.last_error)
    else:
        refund.status = "processing"


def can_fulfill(db, order):
    if order.payment_policy == "manual":
        return True
    if db.scalar(
        select(Issue).where(
            Issue.order_id == order.id,
            ~Issue.resolved,
            Issue.code.in_(["external_refund", "payment_mismatch"]),
        )
    ):
        return False
    payment = db.get(Payment, order.accepted_payment_id) if order.accepted_payment_id else None
    return bool(
        payment
        and payment.provider_status == "succeeded"
        and payment.state == "known"
        and not payment.refunded_amount
        and not db.scalar(select(Refund).where(Refund.order_id == order.id))
    )


def ensure_can_fulfill(db, order, shipping=False):
    if not can_fulfill(db, order):
        raise BusinessError("payment_required", "Нет подтверждённой оплаты или начат возврат")
    if shipping and db.scalar(
        select(Receipt).where(
            Receipt.order_id == order.id, Receipt.kind == "prepayment", Receipt.status == "failed"
        )
    ):
        raise BusinessError("receipt_failed", "Сначала устраните ошибку чека предоплаты")


def order_finances(db, order, manager=False):
    payments = list(
        db.scalars(select(Payment).where(Payment.order_id == order.id).order_by(Payment.created_at))
    )
    refunds = list(
        db.scalars(select(Refund).where(Refund.order_id == order.id).order_by(Refund.created_at))
    )
    active = next((p for p in payments if p.active), None)
    records = []
    for r in refunds:
        attempts = list(
            db.scalars(
                select(RefundAttempt)
                .where(RefundAttempt.refund_id == r.id)
                .order_by(RefundAttempt.created_at)
            )
        )
        records.append(
            {
                "id": r.id,
                "amount": money(r.amount),
                "status": r.status,
                "reason": r.reason,
                "attempts": [
                    {
                        "id": a.id,
                        "status": a.provider_status,
                        "state": a.state,
                        "error": a.last_error,
                        "provider_id": a.provider_id,
                    }
                    for a in attempts
                ],
                "can_retry": r.status == "needs_attention"
                and not any(a.active or a.state == "blocked" for a in attempts),
            }
        )
    issues = [
        {"id": i.id, "code": i.code, "message": i.message, "created_at": i.created_at.isoformat()}
        for i in db.scalars(select(Issue).where(Issue.order_id == order.id, ~Issue.resolved))
    ]
    receipts = [
        {
            "id": r.id,
            "kind": r.kind,
            "status": r.status,
            "test": True,
            "delivery_status": r.delivery_status,
            "error": r.last_error,
        }
        for r in db.scalars(select(Receipt).where(Receipt.order_id == order.id))
    ]
    reservation = db.get(Reservation, order.id)
    accepted = db.get(Payment, order.accepted_payment_id) if order.accepted_payment_id else None
    return {
        "payment_policy": order.payment_policy,
        "accepted_payment_id": order.accepted_payment_id,
        "provider": settings().payment_provider,
        "payments": [
            {
                "id": p.id,
                "status": p.provider_status,
                "state": p.state,
                "amount": money(p.amount),
                "refunded_amount": money(p.refunded_amount),
                "confirmation_url": p.confirmation_url
                if p.active
                and p.state == "known"
                and order.status == "placed"
                and reservation.expires_at > now()
                else None,
                "provider_id": p.provider_id,
                "error": p.last_error,
                "checked_at": p.last_checked_at.isoformat() if p.last_checked_at else None,
            }
            for p in payments
        ],
        "refunds": records,
        "receipts": receipts,
        "issues": issues
        if manager
        else [
            {"code": i["code"], "message": "Состояние операции проверяет менеджер"} for i in issues
        ],
        "actions": {
            "pay": order.payment_policy == "online"
            and not any(p.state == "blocked" for p in payments)
            and order.status == "placed"
            and reservation.status == "held"
            and reservation.expires_at > now()
            and not order.accepted_payment_id
            and (not active or (active.state == "known" and bool(active.confirmation_url))),
            "refund": manager
            and order.status in ("placed", "packing", "canceled")
            and bool(accepted and not accepted.refunded_amount)
            and (not refunds or any(r.status == "approval_required" for r in refunds)),
            "start_packing": order.status == "placed"
            and can_fulfill(db, order)
            and (reservation.status == "allocated" or reservation.expires_at > now()),
            "ship": order.status == "packing"
            and can_fulfill(db, order)
            and not any(r["status"] == "failed" and r["kind"] == "prepayment" for r in receipts),
        },
    }
