import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, text

from app.core.config import settings
from app.core.errors import BusinessError
from app.models import OperationEvent, Order, OrderItem, Reservation
from app.models.store import now
from app.repositories import store as repo


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def money(value):
    return format(value, ".2f")


def event(db, order, action, actor, **details):
    db.add(OperationEvent(order_id=order.id, action=action, actor=actor, details=details))


def quote(db, basket, lock=False):
    quantities = {}
    for line in basket.items:
        quantities[line.product_id] = quantities.get(line.product_id, 0) + line.quantity
    products = repo.products(db, quantities, lock)
    if len(products) != len(quantities):
        raise BusinessError("product_missing", "Товар больше недоступен")
    lines = []
    for p in products:
        q = quantities[p.id]
        if q > 50 or p.stock - p.reserved < q:
            raise BusinessError("out_of_stock", f"Недостаточно товара «{p.name}»")
        lines.append(
            {
                "product_id": p.id,
                "name": p.name,
                "quantity": q,
                "price": money(p.price),
                "total": money(p.price * q),
            }
        )
    subtotal = sum((Decimal(i["total"]) for i in lines), Decimal(0))
    delivery = Decimal("300.00")
    data = {
        "items": lines,
        "subtotal": money(subtotal),
        "delivery": money(delivery),
        "total": money(subtotal + delivery),
    }
    return {**data, "quote_hash": digest(data)}, products


def create_order(db, payload, owner):
    # Serialize only duplicate checkouts for this guest, including first insertion.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": owner + payload.checkout_key},
    )
    request_hash = digest(payload.model_dump())
    old = db.scalar(
        select(Order).where(Order.owner_id == owner, Order.checkout_key == payload.checkout_key)
    )
    if old:
        if old.request_hash != request_hash:
            raise BusinessError(
                "idempotency_conflict", "Ключ оформления уже использован с другими данными"
            )
        return old
    data, products = quote(db, payload, lock=True)
    if data["quote_hash"] != payload.quote_hash:
        raise BusinessError("price_changed", "Стоимость изменилась. Проверьте новый расчёт")
    number = db.scalar(text("SELECT nextval('order_numbers')"))
    order = Order(
        owner_id=owner,
        checkout_key=payload.checkout_key,
        request_hash=request_hash,
        number=number,
        customer_name=payload.customer_name.strip(),
        email=str(payload.email),
        address=payload.address.strip(),
        subtotal=Decimal(data["subtotal"]),
        delivery=Decimal(data["delivery"]),
        total=Decimal(data["total"]),
    )
    db.add(order)
    db.flush()
    for line, product in zip(data["items"], products, strict=True):
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                name=product.name,
                price=product.price,
                quantity=line["quantity"],
            )
        )
        product.reserved += line["quantity"]
    db.add(
        Reservation(
            order_id=order.id, expires_at=now() + timedelta(minutes=settings().reservation_minutes)
        )
    )
    event(db, order, "order_created", "customer", total=money(order.total))
    return order


def change_stock(db, order, consume=False):
    lines = repo.items(db, order.id)
    products = repo.products(db, [i.product_id for i in lines], lock=True)
    for line, product in zip(lines, products, strict=True):
        product.reserved -= line.quantity
        if consume:
            product.stock -= line.quantity


def cancel(db, order, reason, actor):
    if order.status == "canceled":
        return order
    if order.status not in ("placed", "packing") or (
        actor == "customer" and order.status != "placed"
    ):
        raise BusinessError("cannot_cancel", "На этом этапе отмену нужно согласовать с менеджером")
    reservation = db.get(Reservation, order.id)
    if order.status == "packing":
        reservation.status = "release_pending"
    else:
        change_stock(db, order)
        reservation.status = "released"
    order.status = "canceled"
    order.cancel_reason = reason
    event(db, order, "order_canceled", actor, reason=reason)
    return order


def transition(db, order, action):
    reservation = db.get(Reservation, order.id)
    if action == "start-packing":
        if order.status != "placed":
            raise BusinessError("invalid_transition", "Заказ нельзя передать в комплектацию")
        if reservation.expires_at <= now():
            raise BusinessError("reservation_expired", "Срок резерва истёк")
        order.status, reservation.status = "packing", "allocated"
    elif action == "ship":
        if order.status != "packing":
            raise BusinessError("invalid_transition", "Сначала начните комплектацию")
        change_stock(db, order, consume=True)
        order.status, reservation.status = "shipped", "consumed"
    elif action == "complete":
        if order.status != "shipped":
            raise BusinessError("invalid_transition", "Заказ ещё не передан в доставку")
        order.status = "completed"
    elif action == "release-stock":
        if reservation.status != "release_pending":
            raise BusinessError("invalid_transition", "Нет товара, ожидающего возвращения на полку")
        change_stock(db, order)
        reservation.status = "released"
    else:
        raise BusinessError("not_found", "Действие не найдено", 404)
    event(db, order, action, "manager")


def expire_reservations(db):
    ids = list(
        db.scalars(
            select(Reservation.order_id).where(
                Reservation.status == "held", Reservation.expires_at <= now()
            )
        )
    )
    for order_id in ids:
        order = repo.get_order(db, order_id, lock=True)
        if order.status == "placed" and db.get(Reservation, order_id).status == "held":
            cancel(db, order, "Истёк срок резерва", "system")


def order_view(db, order, manager=False):
    reservation = db.get(Reservation, order.id)
    data = {
        "id": order.id,
        "number": order.number,
        "status": order.status,
        "customer_name": order.customer_name,
        "email": order.email,
        "address": order.address,
        "subtotal": money(order.subtotal),
        "delivery": money(order.delivery),
        "total": money(order.total),
        "created_at": order.created_at.isoformat(),
        "cancel_reason": order.cancel_reason,
        "reservation": {
            "status": reservation.status,
            "expires_at": reservation.expires_at.isoformat(),
        },
        "items": [
            {
                "name": i.name,
                "quantity": i.quantity,
                "price": money(i.price),
                "total": money(i.price * i.quantity),
            }
            for i in repo.items(db, order.id)
        ],
        "actions": {
            "cancel": order.status == "placed" or (manager and order.status == "packing"),
            "start_packing": order.status == "placed" and reservation.expires_at > now(),
            "ship": order.status == "packing",
            "complete": order.status == "shipped",
            "release_stock": reservation.status == "release_pending",
        },
        "payment_policy": "manual",
    }
    if manager:
        data["history"] = [
            {
                "action": e.action,
                "actor": e.actor,
                "details": e.details,
                "at": e.created_at.isoformat(),
            }
            for e in db.scalars(
                select(OperationEvent)
                .where(OperationEvent.order_id == order.id)
                .order_by(OperationEvent.id)
            )
        ]
    return data
