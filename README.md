# Asynchronous payment processing service

Для проекта нужен Python 3.14.

## Установка зависимостей

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Зависимости приложения и Ruff перечислены в `requirements.txt`.
Настройки Ruff находятся в `ruff.toml`.

## Запуск API

Заполните `.env` по образцу `.env.example`, затем запустите инфраструктуру и API:

```bash
docker compose up -d
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

## Проверка кода

```bash
python -m ruff check .
python -m ruff format --check .
```

## Тесты

Набор содержит **27 проверок** на pytest: 14 для API и 13 для обработки платежей
и публикации событий. Несколько сценариев запускаются одной параметризованной функцией.
Docker, работающие PostgreSQL и RabbitMQ для запуска не нужны.

### Запуск

Команды выполняются из корня проекта с активированной `.venv` после установки
зависимостей из `requirements.txt`.

```bash
# Все проверки
python -m pytest -q

# Подробный результат по каждому сценарию
python -m pytest -v

# Только обработка платежей, Outbox и webhook
python -m pytest -v tests/test_payment_processing.py

# Одна группа сценариев retry и DLQ
python -m pytest -v tests/test_payment_processing.py::test_completed_payment_webhook_retry_and_rejection
```

### API — `tests/test_payments_api.py`

| Тест | Что проверяет | Ожидаемый результат | Сценариев |
| --- | --- | --- | ---: |
| `test_rejects_missing_or_invalid_api_key` | POST и GET без ключа и с неверным `X-API-Key` | 401; методы сервиса не вызываются | 4 |
| `test_create_payment_returns_accepted_contract` | Создание платежа и передача ключа из заголовка в сервис | 202; только `payment_id`, `status`, `created_at`; сумма передана как Decimal | 1 |
| `test_create_requires_idempotency_header` | POST без `Idempotency-Key` | 422 с ошибкой заголовка; создание не вызывается | 1 |
| `test_create_rejects_invalid_body` | Неверная валюта, сумма или URL webhook | 422 с ошибкой соответствующего поля | 3 |
| `test_get_payment_returns_details` | Получение платежа в статусах pending, succeeded и failed | 200; подробные данные, метаданные и даты сериализуются корректно | 3 |
| `test_get_unknown_payment_returns_404` | Получение отсутствующего платежа | 404 с сообщением `Payment not found` | 1 |
| `test_get_invalid_uuid_returns_422` | Некорректный UUID в пути | 422; поиск платежа не вызывается | 1 |

### Обработка — `tests/test_payment_processing.py`

| Тест | Что проверяет | Ожидаемый результат | Сценариев |
| --- | --- | --- | ---: |
| `test_payment_creation_and_outbox` | Новый платёж, повторный ключ и конфликт вставки | Outbox создаётся только для нового платежа; при повторе и конфликте возвращается существующий | 3 |
| `test_outbox_is_marked_only_after_success` | Успешная публикация и ошибка брокера | Сообщение persistent; отметка публикации ставится только после успешной отправки | 2 |
| `test_pending_payment_is_saved_before_webhook` | Успешный и неуспешный результат эмуляции шлюза | Статус и дата обработки обновлены; commit выполнен до отправки webhook | 2 |
| `test_completed_payment_webhook_retry_and_rejection` | Успех на первой, второй, третьей отправке и три ошибки HTTP 500 | До трёх отправок, задержки 1 и 2 секунды; после третьей ошибки — reject без requeue; результат платежа не меняется | 4 |
| `test_publication_requires_broker_ack` | Ответы Ack и Nack от брокера | Ack принимается; Nack вызывает ошибку; публикация использует mandatory и тайм-аут | 2 |

### Как устроены проверки

`tests/conftest.py` задаёт тестовую конфигурацию и общие фикстуры. В API-тестах
сервис подменяется через FastAPI `dependency_overrides`. В тестах обработки
подменяются репозитории, сессия БД, HTTP-клиент, брокер и ожидание задержек.
Поэтому проверки не изменяют рабочую БД, не отправляют настоящие webhook
и не ждут реальные интервалы retry.

### Границы покрытия

Тесты проверяют логику приложения с подменами. Конфликт вставки воспроизводится
ответом репозитория, а DLQ проверяется через исключение `RejectMessage(requeue=False)`
и настройки маршрутизации — это не проверка реальной конкурентности или переноса сообщения брокером.

Отдельно на работающем окружении проверяются:

- Транзакции, миграции и уникальность ключа при одновременных запросах к PostgreSQL.
- Доставка сообщений RabbitMQ, фактический перенос в DLQ и восстановление после сбоев.
- Сборка и полный запуск сервиса через Docker Compose.
