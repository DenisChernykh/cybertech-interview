import { useEffect, useState, type FormEvent } from "react"
import { useNavigate, Link } from "react-router-dom"
import { ArrowUpRight, ArrowLeft, ShoppingBag, Plus, Minus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Notice, Loading } from "@/components/feedback"
import { api, ApiError, rub, type Quote, type Order } from "@/lib/api"
import type { Cart } from "@/lib/cart"

export default function Checkout({
  cart,
  change,
  clear,
}: {
  cart: Cart
  change: (id: number, delta: number) => void
  clear: () => void
}) {
  const nav = useNavigate(),
    [quote, setQuote] = useState<Quote | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [key, setKey] = useState(() => crypto.randomUUID())
  const items = Object.entries(cart).map(([id, quantity]) => ({ product_id: Number(id), quantity }))
  useEffect(() => {
    let active = true
    setQuote(null)
    setError("")
    if (items.length)
      api<Quote>("/checkout/quote", { items })
        .then((q) => {
          if (active) setQuote(q)
        })
        .catch((e) => active && setError(e.message))
    return () => {
      active = false
    }
  }, [JSON.stringify(cart)])
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!quote) return
    const form = new FormData(e.currentTarget)
    setBusy(true)
    setError("")
    try {
      await api("/session", {})
      const order = await api<Order>("/orders", {
        items,
        customer_name: form.get("name"),
        email: form.get("email"),
        address: form.get("address"),
        quote_hash: quote.quote_hash,
        checkout_key: key,
      })
      clear()
      nav("/orders/" + order.id)
    } catch (e) {
      const err = e as ApiError
      setError(err.message)
      if (err.code === "price_changed") {
        setQuote(await api<Quote>("/checkout/quote", { items }))
        setKey(crypto.randomUUID())
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="page">
      <Link className="back" to="/">
        <ArrowLeft size={16} /> Продолжить покупки
      </Link>
      <h1>Оформление заказа</h1>
      <Notice message={error} />
      {!items.length ? (
        <div className="empty">
          <ShoppingBag />
          <h2>В корзине пока пусто</h2>
          <Link to="/">Выбрать средства</Link>
        </div>
      ) : (
        <div className="checkout-layout">
          <form onSubmit={submit}>
            <h2>Контакты и доставка</h2>
            <div className="field">
              <Label htmlFor="name">Ваше имя</Label>
              <Input
                id="name"
                name="name"
                required
                minLength={2}
                autoComplete="name"
                placeholder="Как к вам обращаться"
              />
            </div>
            <div className="field">
              <Label htmlFor="email">Электронная почта</Label>
              <Input
                id="email"
                name="email"
                required
                type="email"
                autoComplete="email"
                placeholder="name@example.ru"
              />
            </div>
            <div className="field">
              <Label htmlFor="address">Адрес доставки</Label>
              <Input
                id="address"
                name="address"
                required
                minLength={5}
                autoComplete="street-address"
                placeholder="Город, улица, дом и квартира"
              />
            </div>
            <p className="muted">После оформления средства будут зарезервированы на 30 минут.</p>
            <Button className="primary wide" disabled={busy || !quote}>
              {busy ? "Оформляем…" : "Оформить заказ"}
              <ArrowUpRight size={18} />
            </Button>
          </form>
          <aside className="summary">
            <p className="eyebrow">Ваш заказ</p>
            {quote ? (
              <>
                {quote.items.map((i) => (
                  <div className="cart-line" key={i.product_id}>
                    <div>
                      <strong>{i.name}</strong>
                      <div className="quantity">
                        <button
                          aria-label={"Уменьшить " + i.name}
                          onClick={() => change(i.product_id, -1)}
                        >
                          <Minus size={14} />
                        </button>
                        <span>{i.quantity}</span>
                        <button
                          aria-label={"Добавить " + i.name}
                          onClick={() => change(i.product_id, 1)}
                        >
                          <Plus size={14} />
                        </button>
                      </div>
                    </div>
                    <span>{rub(i.total)}</span>
                  </div>
                ))}
                <div className="sum-row">
                  <span>Средства</span>
                  <span>{rub(quote.subtotal)}</span>
                </div>
                <div className="sum-row">
                  <span>Доставка</span>
                  <span>{rub(quote.delivery)}</span>
                </div>
                <div className="sum-row total">
                  <span>Итого</span>
                  <span>{rub(quote.total)}</span>
                </div>
              </>
            ) : (
              <Loading />
            )}
          </aside>
        </div>
      )}
    </section>
  )
}
