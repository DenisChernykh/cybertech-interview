import secrets

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.core.auth import current, guest, manager, new_session, token_hash
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import BusinessError
from app.models import Order, Product, Session
from app.repositories.store import get_order
from app.schemas import Basket, Checkout, Login, Reason
from app.services import store

router = APIRouter(prefix="/api")


@router.post("/session")
def session(request: Request, response: Response, db: DBSession = Depends(get_db)):
    try:
        return {"owner": current(request, db, "guest").owner_id}
    except BusinessError:
        return {"owner": new_session(db, response, "guest")}


@router.get("/products")
def products(db: DBSession = Depends(get_db)):
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "category": p.category,
            "volume": p.volume,
            "image": p.image,
            "price": store.money(p.price),
            "available": p.stock - p.reserved,
        }
        for p in db.scalars(select(Product).order_by(Product.id))
    ]


@router.post("/checkout/quote")
def quote(payload: Basket, db: DBSession = Depends(get_db)):
    return store.quote(db, payload)[0]


@router.post("/orders", status_code=201)
def create(payload: Checkout, identity=Depends(guest), db: DBSession = Depends(get_db)):
    order = store.create_order(db, payload, identity.owner_id)
    db.commit()
    return store.order_view(db, order)


@router.get("/orders")
def own_orders(identity=Depends(guest), db: DBSession = Depends(get_db)):
    return [
        store.order_view(db, o)
        for o in db.scalars(
            select(Order)
            .where(Order.owner_id == identity.owner_id)
            .order_by(Order.created_at.desc())
            .limit(100)
        )
    ]


def owned(db, order_id, identity, lock=False):
    order = get_order(db, order_id, lock)
    if order.owner_id != identity.owner_id:
        raise BusinessError("not_found", "Заказ не найден", 404)
    return order


@router.get("/orders/{order_id}")
def own_order(order_id: str, identity=Depends(guest), db: DBSession = Depends(get_db)):
    return store.order_view(db, owned(db, order_id, identity))


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str, payload: Reason, identity=Depends(guest), db: DBSession = Depends(get_db)
):
    order = owned(db, order_id, identity, True)
    store.cancel(db, order, payload.reason, "customer")
    db.commit()
    return store.order_view(db, order)


@router.post("/manager/login")
def login(payload: Login, response: Response, db: DBSession = Depends(get_db)):
    if not settings().manager_password or not secrets.compare_digest(
        payload.password.encode(), settings().manager_password.encode()
    ):
        raise BusinessError("unauthorized", "Неверный пароль", 401)
    new_session(db, response, "manager")
    return {"ok": True}


@router.post("/manager/logout")
def logout(
    request: Request, response: Response, identity=Depends(manager), db: DBSession = Depends(get_db)
):
    db.delete(db.get(Session, token_hash(request.cookies["manager_session"])))
    db.commit()
    response.delete_cookie("manager_session")
    return {"ok": True}


@router.get("/manager/orders")
def manager_orders(identity=Depends(manager), db: DBSession = Depends(get_db)):
    return [
        store.order_view(db, o, True)
        for o in db.scalars(select(Order).order_by(Order.created_at.desc()).limit(200))
    ]


@router.get("/manager/orders/{order_id}")
def manager_order(order_id: str, identity=Depends(manager), db: DBSession = Depends(get_db)):
    return store.order_view(db, get_order(db, order_id), True)


@router.post("/manager/orders/{order_id}/cancel")
def manager_cancel(
    order_id: str, payload: Reason, identity=Depends(manager), db: DBSession = Depends(get_db)
):
    order = get_order(db, order_id, True)
    store.cancel(db, order, payload.reason, "manager")
    db.commit()
    return store.order_view(db, order, True)


@router.post("/manager/orders/{order_id}/{action}")
def manager_action(
    order_id: str, action: str, identity=Depends(manager), db: DBSession = Depends(get_db)
):
    order = get_order(db, order_id, True)
    store.transition(db, order, action)
    db.commit()
    return store.order_view(db, order, True)
