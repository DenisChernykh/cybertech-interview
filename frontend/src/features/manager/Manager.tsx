import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Notice, Loading } from "@/components/feedback"
import { OrderList } from "@/features/order/OrderList"
import { api, date, type Order } from "@/lib/api"

export default function Manager() {
  const [problems, setProblems] = useState<{
    issues: { id: number; order_id: string | null; message: string }[]
    reconciliation: { status: string; at: string; stale: boolean } | null
  }>({ issues: [], reconciliation: null })
  const [orders, setOrders] = useState<Order[] | null>(null),
    [login, setLogin] = useState(false),
    [error, setError] = useState(""),
    [filter, setFilter] = useState("all"),
    [busy, setBusy] = useState(false)
  const refresh = useCallback(
    () =>
      Promise.all([api<Order[]>("/manager/orders"), api<typeof problems>("/manager/issues")])
        .then(([o, p]) => {
          setOrders(o)
          setProblems(p)
          setLogin(false)
        })
        .catch((e) => {
          if (e.status === 401) setLogin(true)
          else setError(e.message)
        }),
    [],
  )
  useEffect(() => {
    void refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [refresh])
  async function signIn(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      await api("/manager/login", { password: new FormData(e.currentTarget).get("password") })
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="page manager">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Рабочее пространство</p>
          <h1>Заказы магазина</h1>
        </div>
        {!login && (
          <Button variant="outline" onClick={() => refresh()}>
            <RefreshCw size={16} /> Обновить
          </Button>
        )}
      </div>
      <Notice message={error} />
      {login ? (
        <form className="login" onSubmit={signIn}>
          <h2>Вход для менеджера</h2>
          <div className="field">
            <Label htmlFor="password">Пароль</Label>
            <Input
              id="password"
              name="password"
              type="password"
              required
              autoComplete="current-password"
            />
          </div>
          <Button className="wide" disabled={busy}>
            Войти
          </Button>
        </form>
      ) : orders === null ? (
        <Loading />
      ) : (
        <>
          <div className="filters manager-filters">
            {[
              ["all", "Все заказы"],
              ["issues", "Проблемы"],
              ["ready", "Можно комплектовать"],
              ["placed", "Новые"],
              ["packing", "Комплектация"],
              ["shipped", "Доставка"],
              ["canceled", "Отменённые"],
            ].map(([v, l]) => (
              <button key={v} className={filter === v ? "active" : ""} onClick={() => setFilter(v)}>
                {l}
              </button>
            ))}
          </div>
          {orders.filter(
            (o) =>
              filter === "all" ||
              (filter === "issues"
                ? !!o.issues?.length
                : filter === "ready"
                  ? o.actions.start_packing
                  : o.status === filter),
          ).length ? (
            <OrderList
              manager
              orders={orders.filter(
                (o) =>
                  filter === "all" ||
                  (filter === "issues"
                    ? !!o.issues?.length
                    : filter === "ready"
                      ? o.actions.start_packing
                      : o.status === filter),
              )}
            />
          ) : (
            <div className="empty">
              <h2>В этой группе пока нет заказов</h2>
            </div>
          )}
          <div className="sync-line">
            Сверка:{" "}
            {problems.reconciliation
              ? date(problems.reconciliation.at) +
                " · " +
                (problems.reconciliation.stale
                  ? "давно не выполнялась"
                  : problems.reconciliation.status === "succeeded"
                    ? "завершена"
                    : problems.reconciliation.status === "failed"
                      ? "ошибка"
                      : "выполняется")
              : "ещё не выполнялась"}
          </div>
          {filter === "issues" &&
            problems.issues.map((i) => (
              <div className="issue-line" key={i.id}>
                {i.message}
                {i.order_id && (
                  <>
                    {" "}
                    · <Link to={"/manager/orders/" + i.order_id}>Открыть заказ</Link>
                  </>
                )}
              </div>
            ))}
          <p className="muted">Автоматическое обновление каждые 5 секунд.</p>
          <Button
            variant="ghost"
            onClick={async () => {
              await api("/manager/logout", {})
              setLogin(true)
            }}
          >
            Выйти
          </Button>
        </>
      )}
    </section>
  )
}
