import logging
import smtplib
from copy import deepcopy
from datetime import timedelta
from email.message import EmailMessage as Mail

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.integrations.payments import provider
from app.integrations.payments.base import ProviderRejected, ProviderUncertain
from app.models import Reservation
from app.models.payments import (
    EmailMessage,
    Payment,
    Receipt,
    ReconciliationRun,
    Refund,
    RefundAttempt,
    Webhook,
)
from app.models.store import now
from app.repositories.store import get_order
from app.services import payments as business
from app.services import store

log = logging.getLogger(__name__)


def accept_webhook(db, name, event, object_id):
    kind = "payments" if event.startswith("payment.") else "refunds"
    key = name + ":" + event + ":" + object_id
    db.execute(
        insert(Webhook)
        .values(
            key=key,
            provider=name,
            object_type=kind,
            object_id=object_id,
            processed=False,
            attempts=0,
            next_check_at=now(),
            created_at=now(),
        )
        .on_conflict_do_nothing(index_elements=["key"])
    )


def process_operation(model, object_id, force=False):
    kind = "payments" if model is Payment else "refunds"
    with SessionLocal.begin() as db:
        op = db.get(model, object_id)
        if not op or (not force and op.next_check_at > now()):
            return
        if op.state == "rejected" or (op.provider_status == "canceled"):
            return
        already_sent = op.sent_at is not None
        if not op.provider_id:
            if op.sent_at and now() - op.sent_at >= timedelta(hours=23, minutes=55):
                op.state = "blocked"
                if model is RefundAttempt:
                    refund = db.get(Refund, op.refund_id)
                    refund.status = "needs_attention"
                    order_id = refund.order_id
                else:
                    order_id = op.order_id
                business.issue(
                    db,
                    kind + ":" + op.id,
                    "idempotency_window",
                    "Результат неизвестен более 23ч55м. Автоматический POST остановлен. Сверьте операцию с ЮKassa.",
                    order_id,
                )
                return
            if model is Payment and not op.sent_at:
                order = get_order(db, op.order_id, True)
                reservation = db.get(Reservation, order.id)
                if order.status != "placed" or reservation.expires_at <= now():
                    op.state, op.active, op.last_error = (
                        "rejected",
                        False,
                        "order_no_longer_payable",
                    )
                    return
            op.sent_at = op.sent_at or now()
            op.state = "unknown"
        name, external_id, request, key = (
            op.provider,
            op.provider_id,
            deepcopy(op.request),
            op.idempotency_key,
        )
    try:
        gateway = provider(name)
        raw = gateway.get(kind, external_id) if external_id else gateway.create(kind, request, key)
        with SessionLocal.begin() as db:
            (business.apply_payment if model is Payment else business.apply_refund)(
                db, object_id, raw
            )
            business.resolve(db, kind + ":" + object_id)
    except (
        ProviderUncertain,
        ProviderRejected,
        ValueError,
        KeyError,
        TypeError,
        ArithmeticError,
    ) as exc:
        with SessionLocal.begin() as db:
            op = db.get(model, object_id)
            refund = db.get(Refund, op.refund_id) if model is RefundAttempt else None
            order_id = refund.order_id if refund else op.order_id
            # A refusal on a retry (for example expired credentials) says nothing
            # about the first request whose response was lost.
            rejected = isinstance(exc, ProviderRejected) and not external_id and not already_sent
            op.state = "rejected" if rejected else "unknown"
            if rejected:
                op.active = False
            op.last_error = str(exc)[:500]
            op.next_check_at = now() + timedelta(seconds=30)
            if refund:
                refund.status = "needs_attention" if rejected else "processing"
            business.issue(
                db,
                kind + ":" + op.id,
                "request_rejected" if rejected else "sync_unknown",
                ("Запрос отклонён: " if rejected else "Результат уточняется: ") + str(exc)[:400],
                order_id,
            )


def attach_payment(db, name, raw):
    payment = db.scalar(
        select(Payment).where(Payment.provider == name, Payment.provider_id == raw["id"])
    )
    if not payment:
        attempt_id = raw.get("metadata", {}).get("attempt_id")
        payment = db.get(Payment, attempt_id) if isinstance(attempt_id, str) else None
    if payment and payment.provider == name:
        business.apply_payment(db, payment.id, raw)
        return True
    business.issue(
        db,
        "unmatched-payment:" + name + ":" + raw["id"],
        "unmatched_payment",
        "Платёж провайдера не связан с известной попыткой. Проверьте его в личном кабинете.",
    )
    return False


def attach_refund(db, name, raw):
    attempt = db.scalar(
        select(RefundAttempt).where(
            RefundAttempt.provider == name, RefundAttempt.provider_id == raw["id"]
        )
    )
    if attempt:
        business.apply_refund(db, attempt.id, raw)
        return True
    payment = db.scalar(
        select(Payment).where(
            Payment.provider == name, Payment.provider_id == raw.get("payment_id")
        )
    )
    business.issue(
        db,
        "unmatched-refund:" + name + ":" + raw["id"],
        "external_refund",
        "Найден возврат без локального идентификатора. Сверьте его с попыткой/личным кабинетом; не повторяйте новым ключом.",
        payment.order_id if payment else None,
    )
    return False


def process_webhooks():
    with SessionLocal() as db:
        ids = list(
            db.scalars(
                select(Webhook.id)
                .where(~Webhook.processed, Webhook.next_check_at <= now())
                .order_by(Webhook.id)
                .limit(100)
            )
        )
    for object_id in ids:
        with SessionLocal() as db:
            item = db.get(Webhook, object_id)
            name, kind, external_id = item.provider, item.object_type, item.object_id
        try:
            raw = provider(name).get(kind, external_id)
            with SessionLocal.begin() as db:
                (attach_payment if kind == "payments" else attach_refund)(db, name, raw)
                db.get(Webhook, object_id).processed = True
        except (
            ProviderUncertain,
            ProviderRejected,
            ValueError,
            KeyError,
            TypeError,
            ArithmeticError,
        ) as exc:
            with SessionLocal.begin() as db:
                item = db.get(Webhook, object_id)
                item.attempts += 1
                item.last_error = str(exc)[:500]
                item.next_check_at = now() + timedelta(seconds=60)
                if isinstance(exc, ProviderRejected) and str(exc) == "not_found":
                    item.processed = True


def reconcile(force=False):
    with SessionLocal.begin() as db:
        last = db.scalar(select(ReconciliationRun).order_by(ReconciliationRun.id.desc()))
        if (
            last
            and not force
            and last.started_at > now() - timedelta(seconds=settings().reconciliation_seconds)
        ):
            return
        # A prior running row after process restart is evidence of interruption.
        if last and last.status == "running":
            last.status = "interrupted"
            last.error = "Обработчик был остановлен до окончания сверки"
        run = ReconciliationRun()
        db.add(run)
        db.flush()
        run_id = run.id
        earliest = db.scalar(
            select(Payment.created_at).where(Payment.active).order_by(Payment.created_at).limit(1)
        )
        since = min(now() - timedelta(days=2), earliest or now()).isoformat()
    checked = 0
    try:
        # Separate provider ledgers may remain after configuration changes.
        with SessionLocal() as db:
            names = set(db.scalars(select(Payment.provider).distinct())) | {
                settings().payment_provider
            }
        for name in names:
            for kind, apply in (("payments", attach_payment), ("refunds", attach_refund)):
                for raw in provider(name).list(kind, since):
                    with SessionLocal.begin() as db:
                        apply(db, name, raw)
                    checked += 1
        with SessionLocal.begin() as db:
            run = db.get(ReconciliationRun, run_id)
            run.status, run.finished_at, run.checked = "succeeded", now(), checked
            business.resolve(db, "reconciliation")
    except Exception as exc:
        with SessionLocal.begin() as db:
            run = db.get(ReconciliationRun, run_id)
            run.status, run.finished_at, run.error = "failed", now(), type(exc).__name__
            business.issue(
                db,
                "reconciliation",
                "reconciliation_failed",
                "Сверка не выполнена. Проверьте доступность провайдера и настройки.",
            )


def process_receipts(force=False):
    with SessionLocal() as db:
        ids = (
            list(
                db.scalars(
                    select(Receipt.id)
                    .where(Receipt.status != "registered", Receipt.next_check_at <= now())
                    .limit(100)
                )
            )
            if not force
            else list(db.scalars(select(Receipt.id).where(Receipt.status != "registered")))
        )
    for receipt_id in ids:
        with SessionLocal.begin() as db:
            r = db.get(Receipt, receipt_id)
            p = db.get(Payment, r.payment_id)
            name, kind, external_id, body, key = (
                p.provider,
                r.kind,
                r.provider_id,
                deepcopy(r.request),
                r.idempotency_key,
            )
            related_id = p.provider_id
            if kind == "refund":
                attempt = db.scalar(
                    select(RefundAttempt).where(
                        RefundAttempt.refund_id == r.refund_id,
                        RefundAttempt.provider_status == "succeeded",
                    )
                )
                related_id = attempt.provider_id if attempt else None
            if kind == "final" and not external_id:
                if r.sent_at and now() - r.sent_at >= timedelta(hours=23, minutes=55):
                    business.issue(
                        db,
                        "receipt:" + r.id,
                        "receipt_unknown",
                        "Результат создания чека неизвестен. Сверьте кассу; не создавайте дубликат.",
                        r.order_id,
                    )
                    continue
                r.sent_at = r.sent_at or now()
            r.next_check_at = now() + timedelta(seconds=60)
        try:
            gateway = provider(name)
            if kind == "final":
                raw = (
                    gateway.get("receipts", external_id)
                    if external_id
                    else gateway.create("receipts", body, key)
                )
                state = raw["status"]
                new_id = raw["id"]
            else:
                if not related_id:
                    continue
                raw = gateway.get("payments" if kind == "prepayment" else "refunds", related_id)
                state = raw.get("receipt_registration", "pending")
                new_id = None
            with SessionLocal.begin() as db:
                r = db.get(Receipt, receipt_id)
                r.status = {"succeeded": "registered", "canceled": "failed"}.get(state, "pending")
                r.provider_id = new_id or r.provider_id
                r.last_checked_at = now()
                if r.status == "registered":
                    r.last_error = None
                    business.resolve(db, "receipt:" + r.id)
                elif r.status == "failed" or now() - r.created_at > timedelta(minutes=5):
                    r.last_error = (
                        "Ошибка регистрации"
                        if r.status == "failed"
                        else "Регистрация занимает более 5 минут"
                    )
                    business.issue(
                        db,
                        "receipt:" + r.id,
                        "receipt_failed" if r.status == "failed" else "receipt_delayed",
                        r.last_error + ". Проверьте кассовый сервис.",
                        r.order_id,
                    )
        except (
            ProviderRejected,
            ProviderUncertain,
            ValueError,
            KeyError,
            TypeError,
            ArithmeticError,
        ) as exc:
            with SessionLocal.begin() as db:
                r = db.get(Receipt, receipt_id)
                r.last_error = str(exc)[:500]
                if isinstance(exc, ProviderRejected):
                    r.status = "failed"
                business.issue(
                    db,
                    "receipt:" + r.id,
                    "receipt_unknown",
                    "Проверьте результат регистрации чека: " + str(exc)[:300],
                    r.order_id,
                )


def send_mail():
    with SessionLocal() as db:
        ids = list(
            db.scalars(
                select(EmailMessage.id)
                .where(EmailMessage.status != "accepted", EmailMessage.next_check_at <= now())
                .limit(20)
            )
        )
    for message_id in ids:
        with SessionLocal() as db:
            item = db.get(EmailMessage, message_id)
            message = Mail()
            sender = settings().smtp_sender
            message["From"] = sender
            message["To"] = item.recipient
            message["Subject"] = item.subject
            message["Message-ID"] = f"<list-{item.id}@{sender.rsplit('@', 1)[1]}>"
            message.set_content(item.body)
        try:
            with smtplib.SMTP(settings().smtp_host, settings().smtp_port, timeout=5) as smtp:
                smtp.send_message(message)
            with SessionLocal.begin() as db:
                db.get(EmailMessage, message_id).status = "accepted"
                business.resolve(db, "mail:" + str(message_id))
        except (OSError, smtplib.SMTPException) as exc:
            with SessionLocal.begin() as db:
                item = db.get(EmailMessage, message_id)
                item.attempts += 1
                item.last_error = type(exc).__name__
                item.next_check_at = now() + timedelta(seconds=min(300, 30 * item.attempts))
                business.issue(
                    db,
                    "mail:" + str(item.id),
                    "email_failed",
                    "Подтверждение не принято почтовым сервером; запланирована повторная отправка.",
                    item.order_id,
                )


def tick(force=False, mail=True):
    # Session-level advisory lock serializes worker instances, not customer transactions.
    # Commit the lock-acquisition transaction before any network I/O.
    with engine.connect() as guard:
        locked = guard.scalar(text("SELECT pg_try_advisory_lock(73913841)"))
        guard.commit()
        if not locked:
            return
        try:
            process_webhooks()
            for model in (Payment, RefundAttempt):
                with SessionLocal() as db:
                    stmt = select(model.id).where(
                        model.state != "rejected",
                        model.provider_status.is_distinct_from("canceled"),
                    )
                    if not force:
                        stmt = stmt.where(model.next_check_at <= now())
                    ids = list(db.scalars(stmt.order_by(model.next_check_at).limit(100)))
                for object_id in ids:
                    process_operation(model, object_id, force)
            # Every expiring active payment is checked, even before its normal polling time.
            with SessionLocal() as db:
                expired = list(
                    db.scalars(
                        select(Payment.id)
                        .join(Reservation, Reservation.order_id == Payment.order_id)
                        .where(
                            Payment.active,
                            Reservation.status == "held",
                            Reservation.expires_at <= now(),
                        )
                    )
                )
            for payment_id in expired:
                process_operation(Payment, payment_id, True)
            with SessionLocal.begin() as db:
                store.expire_reservations(db)
            reconcile(force)
            process_receipts(force)
            if mail:
                send_mail()
        finally:
            guard.execute(text("SELECT pg_advisory_unlock(73913841)"))
            guard.commit()
