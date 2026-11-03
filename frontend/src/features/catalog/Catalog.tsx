import { useEffect, useState } from "react"
import { ArrowUpRight, Plus, Minus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Notice, Loading } from "@/components/feedback"
import { api, rub, type Product } from "@/lib/api"
import type { Cart } from "@/lib/cart"

export default function Catalog({
  cart,
  change,
}: {
  cart: Cart
  change: (id: number, delta: number) => void
}) {
  const [products, setProducts] = useState<Product[]>([]),
    [error, setError] = useState(""),
    [filter, setFilter] = useState("Всё")
  useEffect(() => {
    api<Product[]>("/products")
      .then(setProducts)
      .catch((e) => setError(e.message))
  }, [])
  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">Простой ритуал, каждый день</p>
          <h1>
            Меньше лишнего.
            <br />
            <em>Больше заботы.</em>
          </h1>
          <p>
            Четыре средства для понятного ежедневного ухода.
            <br />
            Выберите то, что нужно вашей коже.
          </p>
          <a href="#catalog" className="hero-link">
            Найти свой уход <ArrowUpRight size={20} />
          </a>
        </div>
        <img
          src="/images/collection.jpg"
          alt="Коллекция средств для ежедневного ухода"
          fetchPriority="high"
        />
      </section>
      <section id="catalog" className="catalog page">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Коллекция / 01</p>
            <h2>Основа вашего ухода</h2>
          </div>
          <div className="filters">
            {["Всё", "Очищение", "Увлажнение"].map((f) => (
              <button key={f} className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>
                {f}
              </button>
            ))}
          </div>
        </div>
        <Notice message={error} />
        {!products.length && !error ? (
          <Loading />
        ) : (
          <div className="product-grid">
            {products
              .filter((p) => filter === "Всё" || p.category === filter)
              .map((p, index) => (
                <article className="product" key={p.id}>
                  <div className={"product-visual visual-" + p.id}>
                    <span className="product-number">0{index + 1}</span>
                    <div className={"bottle bottle-" + p.id}>
                      <span className="bottle-brand">лист</span>
                      <span>{p.category}</span>
                      <small>{p.volume}</small>
                    </div>
                    <span className="product-volume">{p.volume}</span>
                  </div>
                  <div className="product-category">{p.category}</div>
                  <h3>{p.name}</h3>
                  <p>{p.description}</p>
                  <div className="product-buy">
                    <strong>{rub(p.price)}</strong>
                    {cart[p.id] ? (
                      <div className="quantity">
                        <button aria-label={"Уменьшить " + p.name} onClick={() => change(p.id, -1)}>
                          <Minus size={15} />
                        </button>
                        <span>{cart[p.id]}</span>
                        <button
                          aria-label={"Добавить " + p.name}
                          disabled={cart[p.id] >= p.available}
                          onClick={() => change(p.id, 1)}
                        >
                          <Plus size={15} />
                        </button>
                      </div>
                    ) : (
                      <Button
                        variant="outline"
                        disabled={!p.available}
                        onClick={() => change(p.id, 1)}
                      >
                        {p.available ? "В корзину" : "Нет в наличии"}
                        <Plus size={15} />
                      </Button>
                    )}
                  </div>
                </article>
              ))}
          </div>
        )}
      </section>
    </>
  )
}
