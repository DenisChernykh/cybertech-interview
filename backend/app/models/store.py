import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC)


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("stock >= reserved AND reserved >= 0"),
        CheckConstraint("price > 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(60))
    volume: Mapped[str] = mapped_column(String(30))
    image: Mapped[str] = mapped_column(String(400))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stock: Mapped[int] = mapped_column(default=20)
    reserved: Mapped[int] = mapped_column(default=0)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    owner_id: Mapped[str] = mapped_column(String(36), default=uid)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("owner_id", "checkout_key"), CheckConstraint("total > 0"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    number: Mapped[int] = mapped_column(unique=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    checkout_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    customer_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    address: Mapped[str] = mapped_column(String(500))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    delivery: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(30), default="placed")
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (UniqueConstraint("order_id", "product_id"), CheckConstraint("quantity > 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(160))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int]
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))


class Reservation(Base):
    __tablename__ = "reservations"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="held")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OperationEvent(Base):
    __tablename__ = "operation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
