import { readFileSync } from "node:fs"
import { test, expect, type Page } from "@playwright/test"

test.setTimeout(100_000)
const password =
  process.env.MANAGER_PASSWORD ||
  readFileSync("../.env", "utf8")
    .split("\n")
    .find((line) => line.startsWith("MANAGER_PASSWORD="))
    ?.slice(17)
    .trim()

async function checkout(page: Page) {
  await page.goto("/")
  await page.getByRole("button", { name: "В корзину" }).first().click()
  await page.getByRole("link", { name: /Корзина/ }).click()
  await page.getByLabel("Ваше имя").fill("Анна Браузерная")
  await page.getByLabel("Электронная почта").fill("browser@example.com")
  await page.getByLabel("Адрес доставки").fill("Екатеринбург, Ленина, 10")
  await page.getByRole("button", { name: "Оформить заказ" }).click()
  await expect(page.getByRole("heading", { name: /Заказ №/ })).toBeVisible()
  return new URL(page.url()).pathname
}
async function openPayment(page: Page) {
  await page
    .getByRole("button", { name: /^(Оплатить |Повторить оплату|Продолжить оплату)/ })
    .click()
  await expect(page.getByRole("heading", { name: "Тестовая оплата" })).toBeVisible({
    timeout: 20_000,
  })
}
async function login(page: Page) {
  if (!password) throw new Error("Run scripts/init-env.py or set MANAGER_PASSWORD")
  await page.goto("/manager")
  await expect(page.getByRole("heading", { name: "Вход для менеджера" })).toBeVisible()
  await page.getByLabel("Пароль", { exact: true }).fill(password)
  await page.getByRole("button", { name: "Войти", exact: true }).click()
  await expect(page.getByRole("button", { name: "Можно комплектовать" })).toBeVisible()
}
async function confirm(page: Page) {
  await page.getByRole("button", { name: "Подтвердить тестовую оплату" }).click()
  await expect(page.getByRole("heading", { name: "Оплата получена" })).toBeVisible({
    timeout: 75_000,
  })
}
async function refund(page: Page) {
  await page.getByRole("button", { name: "Вернуть всю оплату" }).click()
  await page
    .getByRole("dialog")
    .getByLabel("Причина возврата")
    .fill("Полный возврат по просьбе покупателя")
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Подтвердить возврат", exact: true })
    .click()
  await expect(page.getByRole("button", { name: "Подтвердить возврат · Mock" })).toBeVisible({
    timeout: 15_000,
  })
}

test("paid order, manager fulfillment and final receipt", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  const path = await checkout(page)
  await openPayment(page)
  await confirm(page)
  await expect(page.getByText("Чек предоплаты", { exact: true })).toBeVisible()
  await page.screenshot({ path: "../artifacts/payment-confirmed.png", fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: "../artifacts/payment-mobile.png", fullPage: true })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await login(page)
  await page.getByRole("button", { name: "Можно комплектовать" }).click()
  await expect(page.locator(`a[href="/manager${path}"]`)).toBeVisible()
  await page.screenshot({ path: "../artifacts/manager-list.png", fullPage: true })
  await page.goto("/manager" + path)
  await page.getByRole("button", { name: "Начать комплектацию" }).click()
  await page.getByRole("button", { name: "Передать в доставку" }).click()
  await page.getByRole("button", { name: "Подтвердить получение" }).click()
  await expect(
    page.locator(".receipt-row").filter({ hasText: "Чек полного расчёта" }),
  ).toContainText("Зарегистрирован", { timeout: 15_000 })
  await expect(page.locator(".status-completed")).toContainText("Получен")
  await page.screenshot({ path: "../artifacts/manager-order.png", fullPage: true })
  expect(errors).toEqual([])
})

test("decline, retry, failed refund and successful retry", async ({ page }) => {
  const path = await checkout(page)
  await openPayment(page)
  await page.getByRole("button", { name: "Отклонить платёж", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Платёж отклонён" })).toBeVisible({
    timeout: 15_000,
  })
  await openPayment(page)
  await confirm(page)
  await login(page)
  await page.goto("/manager" + path)
  await refund(page)
  await page.getByRole("button", { name: "Отклонить возврат · Mock" }).click()
  // A canceled refund has no YooKassa webhook: the worker must discover it through GET.
  await expect(page.getByRole("heading", { name: "Возврат требует внимания" })).toBeVisible({
    timeout: 75_000,
  })
  await page.screenshot({ path: "../artifacts/refund-problem.png", fullPage: true })
  await page.getByRole("button", { name: "Повторить возврат", exact: true }).click()
  await expect(page.getByRole("button", { name: "Подтвердить возврат · Mock" })).toBeVisible({
    timeout: 15_000,
  })
  await page.getByRole("button", { name: "Подтвердить возврат · Mock" }).click()
  await expect(page.getByRole("heading", { name: "Возврат выполнен" })).toBeVisible({
    timeout: 15_000,
  })
  await page.goto(path)
  await expect(page.getByRole("heading", { name: "Возврат выполнен" })).toBeVisible()
})

test("closed payment page and missing webhook recover without buyer requests", async ({
  page,
  context,
}) => {
  const path = await checkout(page)
  await openPayment(page)
  await page.getByText("Проблемные сценарии", { exact: true }).click()
  await page.getByLabel("Не доставлять webhook").check()
  await page.getByRole("button", { name: "Подтвердить тестовую оплату" }).click()
  await page.close()
  const managerPage = await context.newPage()
  await login(managerPage)
  await managerPage.goto("/manager" + path)
  await expect(managerPage.getByRole("heading", { name: "Оплата получена" })).toBeVisible({
    timeout: 75_000,
  })
  await expect(managerPage.getByRole("button", { name: "Начать комплектацию" })).toBeVisible()
  await refund(managerPage)
  await managerPage.getByRole("button", { name: "Подтвердить возврат · Mock" }).click()
  await expect(managerPage.getByRole("heading", { name: "Возврат выполнен" })).toBeVisible({
    timeout: 15_000,
  })
})

test("canceled order plus late payment becomes refund obligation", async ({ page, context }) => {
  const path = await checkout(page)
  await openPayment(page)
  const buyer = await context.newPage()
  await buyer.goto(path)
  await buyer.getByRole("button", { name: "Отменить заказ" }).click()
  await buyer.getByLabel("Причина отмены").fill("Отмена до подтверждения банка")
  await buyer.getByRole("button", { name: "Подтвердить отмену", exact: true }).click()
  await expect(buyer.getByRole("heading", { name: "Заказ отменён" })).toBeVisible()
  await confirm(page)
  await expect(page.getByRole("heading", { name: "Заказ отменён" })).toBeVisible()
  await login(buyer)
  await buyer.goto("/manager" + path)
  await expect(buyer.getByRole("button", { name: "Подтвердить возврат · Mock" })).toBeVisible({
    timeout: 15_000,
  })
  await expect(buyer.getByRole("button", { name: "Начать комплектацию" })).toHaveCount(0)
  await buyer.getByRole("button", { name: "Подтвердить возврат · Mock" }).click()
  await expect(buyer.getByRole("heading", { name: "Возврат выполнен" })).toBeVisible({
    timeout: 15_000,
  })
})

test("receipt failure blocks shipment and manager can recover it", async ({ page }) => {
  const path = await checkout(page)
  await openPayment(page)
  await page.getByText("Проблемные сценарии", { exact: true }).click()
  await page.getByLabel("Результат регистрации чека").selectOption("canceled")
  await confirm(page)
  await login(page)
  await page.goto("/manager" + path)
  await page.getByRole("button", { name: "Начать комплектацию" }).click()
  await expect(page.getByRole("button", { name: "Передать в доставку" })).toHaveCount(0)
  await page.getByRole("button", { name: "Касса восстановлена · Mock" }).click()
  await expect(page.getByRole("button", { name: "Передать в доставку" })).toBeVisible({
    timeout: 15_000,
  })
  await refund(page)
  await page.getByRole("button", { name: "Подтвердить возврат · Mock" }).click()
  await page.getByRole("button", { name: "Товар возвращён на полку" }).click()
  await page.getByRole("button", { name: "Подтвердить возврат на полку", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Возврат выполнен" })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByRole("heading", { name: "Резерв освобождён" })).toBeVisible()
})

test("another browser cannot view or pay for a buyer's order", async ({
  page,
  browser,
  baseURL,
}) => {
  const path = await checkout(page)
  const stranger = await browser.newContext({ baseURL })
  const other = await stranger.newPage()
  await other.goto("/orders")
  await expect(other.getByRole("heading", { name: "Здесь появятся ваши заказы" })).toBeVisible()
  await other.goto(path)
  await expect(other.getByRole("alert")).toContainText("Заказ не найден")
  const pay = await other.request.post("/api" + path + "/payments", {
    headers: { Origin: new URL(baseURL!).origin },
    data: {},
  })
  expect(pay.status()).toBe(404)
  await other.goto("/manager")
  await expect(other.getByRole("heading", { name: "Вход для менеджера" })).toBeVisible()
  await stranger.close()
  await page.getByRole("button", { name: "Отменить заказ" }).click()
  await page.getByLabel("Причина отмены").fill("Проверка доступа завершена")
  await page.getByRole("button", { name: "Подтвердить отмену", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Заказ отменён" })).toBeVisible()
})
