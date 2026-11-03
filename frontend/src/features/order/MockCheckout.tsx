import { useEffect, useState } from "react"
import { Link, useParams, useNavigate } from "react-router-dom"
import { ShieldCheck, ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { api, rub } from "@/lib/api"
type MockPayment = {
  id: string
  order_id: string
  number: number
  amount: string
  provider_status: string
}
export default function MockCheckout() {
  const { id } = useParams(),
    navigate = useNavigate()
  const [payment, setPayment] = useState<MockPayment | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notify, setNotify] = useState(true),
    [receipt, setReceipt] = useState("succeeded")
  useEffect(() => {
    api<MockPayment>("/demo/payments/" + id)
      .then(setPayment)
      .catch((e) => setError(e.message))
  }, [id])
  async function decide(outcome: string) {
    setBusy(true)
    setError("")
    try {
      await api("/demo/payments/" + id, { outcome, notify, receipt_status: receipt })
      navigate("/orders/" + payment!.order_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="page mock-page">
      <div className="mock-content">
        <ShieldCheck size={32} />
        <p className="eyebrow">MockPaymentProvider</p>
        <h1>Тестовая оплата</h1>
        <p>Деньги не списываются. Данные банковской карты не нужны.</p>
        {error && (
          <div className="notice" role="alert">
            {error}
          </div>
        )}
        {payment && (
          <>
            <div className="mock-amount">
              <small>Заказ № {payment.number}</small>
              <strong>{rub(payment.amount)}</strong>
            </div>
            {payment.provider_status === "pending" ? (
              <>
                <Button className="wide" disabled={busy} onClick={() => decide("succeeded")}>
                  Подтвердить тестовую оплату
                </Button>
                <Button
                  className="wide"
                  variant="outline"
                  disabled={busy}
                  onClick={() => decide("canceled")}
                >
                  Отклонить платёж
                </Button>
                <details className="scenario-options">
                  <summary>Проблемные сценарии</summary>
                  <Label className="checkbox-line">
                    <input
                      type="checkbox"
                      checked={!notify}
                      onChange={(e) => setNotify(!e.target.checked)}
                    />{" "}
                    Не доставлять webhook
                  </Label>
                  <Label htmlFor="receipt-result">Результат регистрации чека</Label>
                  <select
                    id="receipt-result"
                    value={receipt}
                    onChange={(e) => setReceipt(e.target.value)}
                  >
                    <option value="succeeded">Зарегистрирован (тест)</option>
                    <option value="canceled">Ошибка регистрации</option>
                    <option value="pending">Регистрация задерживается</option>
                  </select>
                  <p className="muted">
                    Без webhook магазин обнаружит оплату при сверке. Можно закрыть страницу или
                    отменить заказ в другой вкладке, затем подтвердить эту оплату.
                  </p>
                </details>
              </>
            ) : (
              <p className="notice">
                Операция уже завершена:{" "}
                {payment.provider_status === "succeeded" ? "успешно" : "отменена"}.
              </p>
            )}
            <Link className="back" to={"/orders/" + payment.order_id}>
              <ArrowLeft size={16} /> Вернуться к заказу
            </Link>
          </>
        )}
      </div>
    </section>
  )
}
