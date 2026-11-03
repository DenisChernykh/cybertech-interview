# Лист — магазин и интеграция ЮKassa

Демонстрационный проект для технического собеседования: внедрение оплаты в существующий магазин с отдельными состояниями заказа, денег, возврата и чеков.

## Текущий этап

Базовая версия сохранена как `store-v0`. Следующим этапом добавлены серверные платежные сущности, MockPaymentProvider, сверка, возвраты, состояния чеков и восстанавливаемый обработчик. 19 тестов backend проходят. HTTP-адаптер ЮKassa добавлен отдельно: контрактные проверки запросов, ошибок и пагинации проходят. Внешние операции ЮKassa не проверялись: реквизиты не предоставлены. Платёжные экраны добавляются следующим этапом.

## Запуск

```sh
python3 scripts/init-env.py
docker compose up --build -d
```

Магазин: http://localhost:8080, менеджер: http://localhost:8080/manager. Пароль менеджера создаётся в локальном `.env` (MANAGER_PASSWORD). Почта: http://localhost:8026. Не публикуйте `.env`.

Локальная разработка: запустите `docker compose up -d db mail`, затем в `backend` выполните `uv sync`, `uv run alembic upgrade head`, `uv run python -m app.seed`, `uv run uvicorn app.main:app --port 8019`. В другом терминале запустите `uv run python -m app.worker`. В `frontend`: `pnpm install`, `pnpm dev`. Интерфейс: http://localhost:5179. Node 24 (>=24.18.0), pnpm 11.15.1, Python 3.13.

## Проверки базовой версии

Создайте отдельную БД: `docker compose exec db createdb -U shop shop_test`. В `backend` примените миграции с `DATABASE_URL=postgresql+psycopg://shop:local-demo-only@localhost:55439/shop_test uv run alembic upgrade head`, затем `uv run python -m pytest -q` и `uv run ruff check app tests`.

В `frontend`: `pnpm exec playwright install chromium`, `pnpm test` при запущенных API и Vite, `pnpm build`. Тесты PostgreSQL очищают только выделенную БД с суффиксом `_test`. При изменении пароля БД задайте TEST_DATABASE_URL.

Фактически проверены: 6 PostgreSQL-тестов, 3 браузерных проверки, TypeScript/Vite build. Браузерные проверки включают оформление, повторное открытие заказа, отмену и мобильный экран. Docker-сборка всего приложения проверяется на финальном этапе.

## Ограничения основы

Ручное согласование заказа менеджером; нет эквайринга, возвратов денег и фискализации. Гостевой доступ привязан к браузерной сессии (30 дней); восстановление после удаления cookies и регистрация пользователя вне MVP. Изображения иллюстративные. Подсеть Docker задаётся SHOP_SUBNET, по умолчанию 10.246.73.0/24.

- [Бизнес-требования](BUSINESS_REQUIREMENTS.md)
- [Архитектура](ARCHITECTURE.md)

История: документация → базовый магазин (`store-v0`) → платежная интеграция отдельными коммитами. Все платежные демонстрации используют Mock или тестовый магазин ЮKassa. Настоящих списаний и фискальных документов нет.
