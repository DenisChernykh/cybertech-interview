import { useState } from "react"
import { Link, Route, Routes } from "react-router-dom"
import { Leaf, ShoppingBag } from "lucide-react"
import { loadCart, type Cart } from "@/lib/cart"
import Catalog from "@/features/catalog/Catalog"
import Checkout from "@/features/checkout/Checkout"
import MyOrders from "@/features/order/OrderList"
import OrderPage from "@/features/order/OrderPage"
import MockCheckout from "@/features/order/MockCheckout"
import Manager from "@/features/manager/Manager"

export default function App() {
  const [cart, setCart] = useState<Cart>(loadCart)
  const change = (id: number, delta: number) =>
    setCart((old) => {
      const next = { ...old, [id]: Math.max(0, (old[id] || 0) + delta) }
      if (!next[id]) delete next[id]
      localStorage.setItem("list-cart", JSON.stringify(next))
      return next
    })
  const clear = () => {
    setCart({})
    localStorage.removeItem("list-cart")
  }
  const count = Object.values(cart).reduce((a, b) => a + b, 0)
  return (
    <>
      <header className="header">
        <Link className="brand" to="/">
          <Leaf size={26} strokeWidth={1.3} /> лист<span>ежедневный уход</span>
        </Link>
        <nav aria-label="Главное меню">
          <Link to="/orders">Мои заказы</Link>
          <Link to="/manager">Менеджер</Link>
          <Link className="bag" to="/checkout">
            <ShoppingBag size={19} />
            <span>Корзина</span>
            <b>{count}</b>
          </Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Catalog cart={cart} change={change} />} />
          <Route
            path="/checkout"
            element={<Checkout cart={cart} change={change} clear={clear} />}
          />
          <Route path="/orders" element={<MyOrders />} />
          <Route path="/orders/:id" element={<OrderPage />} />
          <Route path="/manager" element={<Manager />} />
          <Route path="/demo/payments/:id" element={<MockCheckout />} />
          <Route path="/manager/orders/:id" element={<OrderPage manager />} />
          <Route
            path="*"
            element={
              <section className="page">
                <h1>Страница не найдена</h1>
                <Link to="/">В магазин</Link>
              </section>
            }
          />
        </Routes>
      </main>
      <footer>
        <span className="brand">лист</span>
        <span>Небольшие привычки. Забота о себе.</span>
      </footer>
    </>
  )
}
