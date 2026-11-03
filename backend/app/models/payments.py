from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.store import Base, now, uid


class ExternalOperation:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(30))
    provider_id: Mapped[str | None] = mapped_column(String(100))
    provider_status: Mapped[str | None] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, default=uid)
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="queued")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, index=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Payment(ExternalOperation, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id"),
        Index("one_active_payment", "order_id", unique=True, postgresql_where=text("active")),
    )
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    confirmation_url: Mapped[str | None] = mapped_column(String(1500))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="requested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RefundAttempt(ExternalOperation, Base):
    __tablename__ = "refund_attempts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id"),
        Index("one_active_refund", "refund_id", unique=True, postgresql_where=text("active")),
    )
    refund_id: Mapped[str] = mapped_column(ForeignKey("refunds.id"), index=True)


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_key: Mapped[str] = mapped_column(String(100), unique=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"))
    refund_id: Mapped[str | None] = mapped_column(ForeignKey("refunds.id"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="planned")
    provider_id: Mapped[str | None] = mapped_column(String(100))
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(64), default=uid)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    delivery_status: Mapped[str] = mapped_column(String(30), default="not_confirmed")
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Issue(Base):
    __tablename__ = "issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(180), unique=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(String(1000))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(180), unique=True)
    provider: Mapped[str] = mapped_column(String(30))
    object_type: Mapped[str] = mapped_column(String(20))
    object_id: Mapped[str] = mapped_column(String(100))
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    recipient: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(3000))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    last_error: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(default=0)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    checked: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(500))


class MockObject(Base):
    __tablename__ = "mock_objects"
    __table_args__ = (UniqueConstraint("kind", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
