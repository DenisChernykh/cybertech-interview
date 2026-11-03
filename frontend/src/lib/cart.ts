export type Cart = Record<number, number>
export function loadCart(): Cart {
  try {
    return JSON.parse(localStorage.getItem("list-cart") || "{}")
  } catch {
    return {}
  }
}
