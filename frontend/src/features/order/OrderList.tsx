import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { ArrowUpRight } from "lucide-react"
import { Notice, Loading, Tag } from "@/components/feedback"
import { api, rub, date, type Order } from "@/lib/api"

export default function MyOrders() {
  const [orders, setOrders] = useState<Order[] | null>(null),
    [error, setError] = useState("")
  useEffect(() => {
    api("/session", {})
      .then(() => api<Order[]>("/orders"))
      .then(setOrders)
      .catch((e) => setError(e.message))
  }, [])
  return (
    <section className="page">
      <p className="eyebrow">Личный ритуал</p>
      <h1>Мои заказы</h1>
      <Notice message={error} />
      {orders === null ? (
        <Loading />
      ) : !orders.length ? (
        <div className="empty">
          <h2>Здесь появятся ваши заказы</h2>
          <Link to="/">Перейти в магазин</Link>
        </div>
      ) : (
        <OrderList orders={orders} />
      )}
    </section>
  )
}
export function OrderList({ orders, manager = false }: { orders: Order[]; manager?: boolean }) {
  return (
    <div className="order-list">
      {orders.map((o) => (
        <Link key={o.id} className="order-row" to={(manager ? "/manager" : "") + "/orders/" + o.id}>
          <div>
            <strong>Заказ № {o.number}</strong>
            <small>{date(o.created_at)}</small>
            {o.payment_policy === "online" && (
              <small className="financial-label">
                {o.refunds?.length
                  ? "Возврат: " +
                    ({
                      succeeded: "выполнен",
                      needs_attention: "ошибка",
                      approval_required: "нужно подтверждение",
                      processing: "обрабатывается",
                      requested: "запрошен",
                    }[o.refunds.at(-1)!.status] || "проверяется")
                  : o.payments?.some((p) => p.status === "succeeded")
                    ? "Оплата подтверждена"
                    : o.payments?.at(-1)?.status === "canceled"
                      ? "Оплата отклонена"
                      : "Ожидает оплаты"}
                {!!o.issues?.length && " · Требует внимания"}
              </small>
            )}
          </div>
          <div>{manager ? o.customer_name : o.items.map((i) => i.name).join(", ")}</div>
          <Tag status={o.status} />
          <strong>{rub(o.total)}</strong>
          <ArrowUpRight size={19} />
        </Link>
      ))}
    </div>
  )
}
