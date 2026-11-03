from sqlalchemy import select

from app.core.errors import BusinessError
from app.models import Order, OrderItem, Product


def get_order(db, order_id, lock=False):
    stmt = select(Order).where(Order.id == order_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    order = db.scalar(stmt)
    if not order:
        raise BusinessError("not_found", "Заказ не найден", 404)
    return order


def items(db, order_id):
    return list(
        db.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.product_id)
        )
    )


def products(db, ids, lock=False):
    stmt = select(Product).where(Product.id.in_(ids)).order_by(Product.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return list(db.scalars(stmt))
