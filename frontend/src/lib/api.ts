export class ApiError extends Error {
  constructor(public status: number, message: string, public code = "") { super(message) }
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch("/api" + path, {
    credentials: "same-origin",
    ...(body !== undefined ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {})
  })
  const data = await response.json()
  if (!response.ok) throw new ApiError(response.status, data.message || "Проверьте введённые данные", data.code)
  return data
}
export const rub = (value: string | number) => new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 2 }).format(Number(value))
export const date = (value: string) => new Date(value).toLocaleString("ru-RU")
export type Product = { id: number; name: string; description: string; category: string; volume: string; image: string; price: string; available: number }
export type Quote = { items: {product_id:number;name:string;quantity:number;price:string;total:string}[]; subtotal: string; delivery: string; total: string; quote_hash: string }
export type Order = {
 id:string; number:number; status:string; customer_name:string; email:string; address:string;
 subtotal:string; delivery:string; total:string; created_at:string; cancel_reason:string|null;
 reservation:{status:string;expires_at:string};
 items:{name:string;quantity:number;price:string;total:string}[];
 actions:Record<string,boolean>; payment_policy:string;
 history?:{action:string;actor:string;details:Record<string,unknown>;at:string}[]
}
export const statusName: Record<string,string> = { placed:"Оформлен", packing:"Комплектуется", shipped:"В доставке", completed:"Получен", canceled:"Отменён", held:"Зарезервировано", allocated:"Закреплено за заказом", consumed:"Передано в доставку", released:"Резерв освобождён", release_pending:"Верните товар на полку" }

