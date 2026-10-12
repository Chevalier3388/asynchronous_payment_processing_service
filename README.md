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

```bash
python -m pytest -q
```

Тесты API проверяют ответы POST/GET, валидацию и `X-API-Key` без запуска Docker.
Сервис платежей подменяется тестовым объектом; настройки используют тестовые значения.
Эти тесты не проверяют реальные транзакции PostgreSQL, идемпотентность и доставку Outbox.
