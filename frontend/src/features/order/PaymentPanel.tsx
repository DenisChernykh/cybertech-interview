import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import ActionDialog from "@/components/ActionDialog"
import { api, rub, date, type Order } from "@/lib/api"

const states: Record<string, string> = {
  queued: "Готовим оплату",
  unknown: "Уточняем результат",
  blocked: "Нужна проверка менеджера",
  rejected: "Запрос отклонён",
  pending: "Ожидается подтверждение",
  succeeded: "Оплата подтверждена",
  canceled: "Платёж отклонён",
  requested: "Возврат запрошен",
  processing: "Возврат обрабатывается",
  needs_attention: "Возврат требует внимания",
  approval_required: "Возврат ожидает менеджера",
  registered: "Зарегистрирован",
  failed: "Ошибка регистрации",
  planned: "Подготовлен",
}
const kinds: Record<string, string> = {
  prepayment: "Чек предоплаты",
  final: "Чек полного расчёта",
  refund: "Чек возврата",
}
const errors: Record<string, string> = {
  insufficient_funds: "Недостаточно средств. Попробуйте другую карту.",
  payment_canceled: "Оплата отменена.",
  order_no_longer_payable: "Срок оплаты этого заказа истёк.",
}
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
export default function PaymentPanel({
  order,
  manager,
  refresh,
}: {
  order: Order
  manager: boolean
  refresh: () => void
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [refundOpen, setRefundOpen] = useState(false)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const payments = order.payments || [],
    last = payments.at(-1)
  if (order.payment_policy === "manual")
    return (
      <div className="detail-block">
        <p className="eyebrow">Способ обработки</p>
        <h3>Согласование с менеджером</h3>
        <p className="muted">Заказ оформлен до подключения онлайн-оплаты.</p>
      </div>
    )
  const paid = payments.find((p) => p.status === "succeeded")
  async function pay() {
    setBusy(true)
    setError("")
    try {
      let current = await api<Order>("/orders/" + order.id + "/payments", {})
      refresh()
      for (let i = 0; i < 25; i++) {
        if (!mounted.current) return
        const p = current.payments?.at(-1)
        if (p?.confirmation_url) {
          window.location.assign(p.confirmation_url)
          return
        }
        if (p?.status === "succeeded") {
          refresh()
          return
        }
        if (p?.status === "canceled" || p?.state === "rejected" || p?.state === "blocked")
          throw new Error(
            errors[p.error || ""] || "Не удалось открыть оплату. Проверьте состояние заказа.",
          )
        await wait(500)
        current = await api<Order>("/orders/" + order.id)
      }
      setError("Платёж ещё создаётся. Состояние обновится автоматически.")
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
      refresh()
    }
  }
  async function command(path: string, body: unknown = {}) {
    setBusy(true)
    setError("")
    try {
      await api(path, body)
      refresh()
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="payment-panel">
      <p className="eyebrow">
        Оплата · {order.provider === "mock" ? "Локальная демонстрация" : "ЮKassa · тестовый режим"}
      </p>
      <div className="payment-heading">
        <h2>
          {paid
            ? "Оплата получена"
            : last
              ? states[last.state === "known" ? last.status || last.state : last.state] ||
                "Проверяем оплату"
              : "Заказ ожидает оплаты"}
        </h2>
        <strong>{rub(order.total)}</strong>
      </div>
      {order.status === "canceled" && paid && (
        <p>Заказ отменён. Состояние возврата показано ниже.</p>
      )}
      {!paid && last?.error && (
        <p className="muted">
          {errors[last.error] ||
            "Результат операции проверяется. Если ошибка сохраняется, обратитесь к менеджеру."}
        </p>
      )}
      {error && (
        <p className="notice" role="alert">
          {error}
        </p>
      )}
      {!manager && order.actions.pay && (
        <Button disabled={busy} className="wide" onClick={pay}>
          {busy
            ? "Открываем оплату…"
            : last?.confirmation_url
              ? "Продолжить оплату"
              : payments.length
                ? "Повторить оплату"
                : "Оплатить " + rub(order.total)}
        </Button>
      )}
      {!manager && last && !paid && !order.actions.pay && order.status !== "canceled" && (
        <p className="muted">
          Статус проверяется автоматически. Повторное списание пока недоступно.
        </p>
      )}
      {manager && (
        <div className="actions">
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => command("/manager/orders/" + order.id + "/reconcile")}
          >
            Проверить операции
          </Button>
          {order.actions.refund && (
            <Button
              disabled={busy}
              onClick={() => {
                setError("")
                setRefundOpen(true)
              }}
            >
              Вернуть всю оплату
            </Button>
          )}
        </div>
      )}
      {payments.length > 0 && (
        <details className="attempts">
          <summary>История оплат · {payments.length}</summary>
          {payments.map((p, n) => (
            <div key={p.id}>
              <strong>
                Попытка {n + 1} · {states[p.status || p.state] || p.state}
              </strong>
              <span>{rub(p.amount)}</span>
              {p.checked_at && <small>Проверено: {date(p.checked_at)}</small>}
              {manager && p.provider_id && <small className="mono">{p.provider_id}</small>}
              {Number(p.refunded_amount) > 0 && (
                <small>Возвращено провайдером: {rub(p.refunded_amount)}</small>
              )}
            </div>
          ))}
        </details>
      )}
      {order.refunds?.map((r) => (
        <section className="refund-block" key={r.id}>
          <div className="payment-heading">
            <h3>{r.status === "succeeded" ? "Возврат выполнен" : states[r.status] || r.status}</h3>
            <strong>{rub(r.amount)}</strong>
          </div>
          <p>{r.reason}</p>
          {r.status === "succeeded" && (
            <p className="muted">
              Операция возврата подтверждена. В настоящем магазине срок зачисления зависит от банка.
            </p>
          )}
          {r.status === "needs_attention" && (
            <p className="notice">
              Возврат не завершён. Менеджеру нужно устранить причину и повторить операцию.
            </p>
          )}
          {manager && r.can_retry && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => command("/manager/refunds/" + r.id + "/retry")}
            >
              Повторить возврат
            </Button>
          )}
          {manager &&
            order.provider === "mock" &&
            r.attempts
              .filter((a) => a.provider_id && a.status === "pending")
              .map((a) => (
                <div className="demo-controls" key={a.id}>
                  <p className="eyebrow">Сценарий тестового возврата</p>
                  <div className="actions">
                    <Button
                      disabled={busy}
                      onClick={() =>
                        command("/manager/demo/refunds/" + a.id, { outcome: "succeeded" })
                      }
                    >
                      Подтвердить возврат · Mock
                    </Button>
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() =>
                        command("/manager/demo/refunds/" + a.id, { outcome: "canceled" })
                      }
                    >
                      Отклонить возврат · Mock
                    </Button>
                  </div>
                </div>
              ))}
          {manager && r.attempts.some((a) => a.error) && (
            <p className="muted">
              Причина провайдера: {r.attempts.filter((a) => a.error).at(-1)?.error}
            </p>
          )}
        </section>
      ))}
      {(order.receipts?.length || 0) > 0 && (
        <section className="receipts">
          <h3>Тестовая фискализация</h3>
          <p className="muted">
            Фискальный документ не формируется. Это проверка состояния и данных чека.
          </p>
          {order.receipts?.map((r) => (
            <div className="receipt-row" key={r.id}>
              <span>{kinds[r.kind]}</span>
              <Badge variant="outline">{states[r.status] || r.status}</Badge>
              {manager && order.provider === "mock" && r.status === "failed" && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    command("/manager/demo/receipts/" + r.id, { outcome: "succeeded" })
                  }
                >
                  Касса восстановлена · Mock
                </Button>
              )}
            </div>
          ))}
        </section>
      )}
      {manager &&
        order.issues?.map((i) => (
          <div className="notice" key={i.id}>
            <strong>Требует внимания</strong>
            <p>{i.message}</p>
          </div>
        ))}
      {manager && order.provider === "mock" && order.reservation.status === "held" && (
        <div className="demo-controls">
          <p className="eyebrow">Проверка срока резерва</p>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => command("/manager/demo/orders/" + order.id + "/expire")}
          >
            Завершить резерв · Mock
          </Button>
        </div>
      )}
      <ActionDialog
        open={refundOpen}
        onOpenChange={setRefundOpen}
        title="Полный возврат оплаты"
        description={`К возврату ${rub(order.total)}, включая доставку. Исполнение заказа будет отменено.`}
        reasonLabel="Причина возврата"
        confirmLabel="Подтвердить возврат"
        busy={busy}
        error={error}
        onConfirm={(reason) => command("/manager/orders/" + order.id + "/refunds", { reason })}
      />
    </div>
  )
}
