import { test, expect } from "@playwright/test"

test("catalog, checkout, owner access and cancellation", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Основа вашего ухода" })).toBeVisible()
  await page.getByRole("button", { name: "В корзину" }).first().click()
  await page.getByRole("link", { name: /Корзина/ }).click()
  await page.getByLabel("Ваше имя").fill("Анна Демонстрационная")
  await page.getByLabel("Электронная почта").fill("anna@example.com")
  await page.getByLabel("Адрес доставки").fill("Екатеринбург, улица Ленина, 1")
  await page.getByRole("button", { name: "Оформить заказ" }).click()
  await expect(page.getByRole("heading", { name: /Заказ №/ })).toBeVisible()
  const url = page.url()
  await page.reload()
  await expect(page.getByRole("heading", { name: /Заказ №/ })).toBeVisible()
  page.on("dialog", (dialog) => dialog.accept("Проверка отмены заказа"))
  await page.getByRole("button", { name: "Отменить заказ" }).click()
  await expect(page.getByRole("heading", { name: "Заказ отменён" })).toBeVisible()
  expect(page.url()).toBe(url)
})

test("mobile catalog has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")
  await expect(page.getByRole("button", { name: "В корзину" }).first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: "../artifacts/store-mobile.png", fullPage: true })
})

test("desktop catalog screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/")
  await expect(page.getByRole("button", { name: "В корзину" }).first()).toBeVisible()
  await page.screenshot({ path: "../artifacts/store-desktop.png", fullPage: true })
})
