import { useCallback, useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { ArrowLeft, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Notice, Loading, Tag } from "@/components/feedback"
import ActionDialog from "@/components/ActionDialog"
import PaymentPanel from "./PaymentPanel"
import { api, rub, date, statusName, type Order } from "@/lib/api"

export default function OrderPage({ manager = false }: { manager?: boolean }) {
  const { id } = useParams(),
    [order, setOrder] = useState<Order | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [confirmation, setConfirmation] = useState<"cancel" | "release-stock" | null>(null)
  const path = (manager ? "/manager" : "") + "/orders/" + id
  const refresh = useCallback(
    () =>
      api<Order>(path)
        .then((value) => {
          setOrder(value)
          setError("")
        })
        .catch((e) => setError(e.message)),
    [path],
  )
  useEffect(() => {
    void refresh()
    const timer = setInterval(refresh, 4000)
    return () => clearInterval(timer)
  }, [refresh])
  async function action(name: string, body: unknown = {}) {
    setBusy(true)
    setError("")
    try {
      setOrder(await api<Order>(path + "/" + name, body))
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="page">
      <Link className="back" to={manager ? "/manager" : "/orders"}>
        <ArrowLeft size={16} /> {manager ? "Заказы магазина" : "Мои заказы"}
      </Link>
      <Notice message={error} />
      {!order ? (
        error ? null : (
          <Loading />
        )
      ) : (
        <>
          <div className="section-heading">
            <div>
              <p className="eyebrow">{date(order.created_at)}</p>
              <h1>Заказ № {order.number}</h1>
            </div>
            <Tag status={order.status} />
          </div>
          <div className="checkout-layout">
            <div>
              <div className="state-box">
                <Check size={22} />
                <div>
                  <h2>
                    {(
                      {
                        canceled: "Заказ отменён",
                        packing: "Собираем заказ",
                        shipped: "Заказ в доставке",
                        completed: "Заказ получен",
                      } as Record<string, string>
                    )[order.status] || "Заказ принят"}
                  </h2>
                  <p>
                    {order.cancel_reason ||
                      (order.status === "completed"
                        ? "Спасибо за заказ. Получение подтверждено."
                        : order.status === "shipped"
                          ? "Товары переданы в доставку."
                          : order.payment_policy === "manual"
                            ? "Менеджер согласует с вами детали заказа."
                            : order.accepted_payment_id
                              ? "Оплата подтверждена. Мы готовим ваш заказ."
                              : "Товары зарезервированы. Завершите оплату до окончания резерва.")}
                  </p>
                </div>
              </div>
              <PaymentPanel order={order} manager={manager} refresh={() => void refresh()} />
              <div className="detail-block">
                <p className="eyebrow">Состояние товара</p>
                <h3>{statusName[order.reservation.status]}</h3>
                {order.reservation.status === "held" && (
                  <p>Резерв до {date(order.reservation.expires_at)}</p>
                )}
              </div>
              <div className="detail-block">
                <p className="eyebrow">Доставка</p>
                <p>
                  {order.customer_name}
                  <br />
                  {order.address}
                  <br />
                  {order.email}
                </p>
              </div>
              <div className="actions">
                {manager && order.actions.start_packing && (
                  <Button disabled={busy} onClick={() => action("start-packing")}>
                    Начать комплектацию
                  </Button>
                )}
                {manager && order.actions.ship && (
                  <Button disabled={busy} onClick={() => action("ship")}>
                    Передать в доставку
                  </Button>
                )}
                {manager && order.actions.complete && (
                  <Button disabled={busy} onClick={() => action("complete")}>
                    Подтвердить получение
                  </Button>
                )}
                {manager && order.actions.release_stock && (
                  <Button
                    disabled={busy}
                    onClick={() => {
                      setError("")
                      setConfirmation("release-stock")
                    }}
                  >
                    Товар возвращён на полку
                  </Button>
                )}
                {order.actions.cancel && (
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => {
                      setError("")
                      setConfirmation("cancel")
                    }}
                  >
                    Отменить заказ
                  </Button>
                )}
              </div>
              <ActionDialog
                open={confirmation !== null}
                onOpenChange={(open) => {
                  if (!open) setConfirmation(null)
                }}
                title={confirmation === "cancel" ? "Отмена заказа" : "Возвращение товара на полку"}
                description={
                  confirmation === "cancel"
                    ? "Исполнение заказа будет отменено. Если оплата уже получена, её возврат контролируется отдельно."
                    : "Подтвердите, что все товары этого заказа физически возвращены на полку. После этого они снова будут доступны для продажи."
                }
                reasonLabel={confirmation === "cancel" ? "Причина отмены" : undefined}
                confirmLabel={
                  confirmation === "cancel" ? "Подтвердить отмену" : "Подтвердить возврат на полку"
                }
                busy={busy}
                error={error}
                onConfirm={(reason) =>
                  action(confirmation!, confirmation === "cancel" ? { reason } : {})
                }
              />
            </div>
            <aside className="summary">
              <p className="eyebrow">Состав заказа</p>
              {order.items.map((i, n) => (
                <div className="cart-line" key={n}>
                  <div>
                    <strong>{i.name}</strong>
                    <small>
                      {i.quantity} × {rub(i.price)}
                    </small>
                  </div>
                  <span>{rub(i.total)}</span>
                </div>
              ))}
              <div className="sum-row">
                <span>Доставка</span>
                <span>{rub(order.delivery)}</span>
              </div>
              <div className="sum-row total">
                <span>Итого</span>
                <span>{rub(order.total)}</span>
              </div>
              <p className="muted">
                {order.payment_policy === "manual"
                  ? "Ручная обработка менеджером"
                  : "Полная предоплата · тестовый режим"}
              </p>
            </aside>
          </div>
          {manager && order.history && (
            <div className="history">
              <h2>История заказа</h2>
              {order.history.map((e, n) => (
                <div key={n}>
                  <time>{date(e.at)}</time>
                  <strong>{eventName[e.action] || e.action}</strong>
                  <span>
                    {e.actor === "customer"
                      ? "Покупатель"
                      : e.actor === "manager"
                        ? "Менеджер"
                        : "Система"}
                  </span>
                  <small>
                    {Object.entries(e.details)
                      .map(([k, v]) => (detailName[k] || k) + ": " + String(v))
                      .join(" · ")}
                  </small>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
const eventName: Record<string, string> = {
  order_created: "Заказ оформлен",
  order_canceled: "Заказ отменён",
  "start-packing": "Начата комплектация",
  ship: "Передан в доставку",
  complete: "Получен покупателем",
  "release-stock": "Товар возвращён на полку",
  payment_requested: "Создана попытка оплаты",
  payment_succeeded: "Оплата подтверждена",
  payment_canceled: "Платёж отклонён",
  refund_requested: "Запрошен полный возврат",
  refund_approval_required: "Возврат ожидает согласования",
  refund_approved: "Возврат согласован менеджером",
  refund_retry: "Возврат отправлен повторно",
  refund_failed: "Возврат отклонён провайдером",
  refund_succeeded: "Возврат подтверждён",
}
const detailName: Record<string, string> = {
  total: "Сумма заказа",
  amount: "Сумма",
  reason: "Причина",
  attempt_id: "Попытка",
  provider_id: "Операция провайдера",
  refund_id: "Возврат",
}
