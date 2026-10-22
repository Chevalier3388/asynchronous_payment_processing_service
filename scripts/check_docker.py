"""Проверка реального Docker-окружения; запускается через ./run.sh, не через pytest."""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import aio_pika
import httpx
import uvicorn
from fastapi import FastAPI, Response
from sqlalchemy import func, select

from app.core.config import settings
from app.db.database import async_session_maker, engine
from app.db.models.outbox import Outbox
from app.db.models.payment import Payment

receiver = FastAPI()
received: dict[str, list[dict]] = {}


@receiver.get("/health")
async def health():
    return {"status": "ok"}


@receiver.get("/events/{payment_id}")
async def events(payment_id: str):
    return received.get(payment_id, [])


@receiver.post("/{mode}")
async def webhook(mode: str, payload: dict):
    attempts = received.setdefault(payload["payment_id"], [])
    attempts.append({"time": time.monotonic(), "payload": payload})
    if mode == "timeout":
        await asyncio.sleep(12)
    failures = {"fail": 3, "retry2": 1, "retry3": 2}.get(mode, 0)
    return Response(status_code=500 if len(attempts) <= failures else 200)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def passed(message: str) -> None:
    print(f"PASS: {message}", flush=True)


async def wait_for(check, description: str, timeout: float = 90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await check()
        if result:
            return result
        await asyncio.sleep(0.5)
    raise AssertionError(f"Истекло время ожидания: {description}")


class DockerCheck:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.api = "http://api:8000/api/v1/payments"
        self.receiver = "http://" + os.environ["CHECK_RECEIVER"] + ":9000"
        self.run_id = os.environ["CHECK_RUN_ID"]
        self.headers = {"X-API-Key": settings.api_key}

    async def ready(self):
        async def probe():
            try:
                api = await self.client.get(f"{self.api}/{uuid4()}")
                receiver_response = await self.client.get(self.receiver + "/health")
                return api.status_code == 401 and receiver_response.status_code == 200
            except httpx.RequestError:
                return False

        await wait_for(probe, "готовность API и получателя")

    def body(self, mode: str):
        url = self.receiver + "/" + mode
        if mode == "unreachable":
            url = "http://" + os.environ["CHECK_RECEIVER"] + ":9999/ok"
        return {
            "amount": "123.45",
            "currency": "RUB",
            "description": "Автоматическая проверка Docker",
            "metadata": {"check_run": self.run_id},
            "webhook_url": url,
        }

    async def create(self, label: str, mode: str = "ok"):
        response = await self.client.post(
            self.api,
            headers={**self.headers, "Idempotency-Key": f"{self.run_id}-{label}"},
            json=self.body(mode),
        )
        require(response.status_code == 202, f"POST {label}: ожидался 202")
        data = response.json()
        require(set(data) == {"payment_id", "status", "created_at"}, "Контракт POST")
        # Немедленный GET проверяет, что ответ POST отправлен после commit.
        await self.get(data["payment_id"])
        return data

    async def get(self, payment_id: str):
        response = await self.client.get(f"{self.api}/{payment_id}", headers=self.headers)
        require(response.status_code == 200, f"GET {payment_id}: ожидался 200")
        return response.json()

    async def receipts(self, payment_id: str):
        response = await self.client.get(f"{self.receiver}/events/{payment_id}")
        require(response.status_code == 200, "Получатель недоступен")
        return response.json()

    @staticmethod
    def check_payload(payment: dict, items: list[dict]):
        processed_at = datetime.fromisoformat(payment["processed_at"]).astimezone(UTC)
        expected = {
            "payment_id": payment["id"],
            "status": payment["status"],
            "amount": payment["amount"],
            "currency": payment["currency"],
            "processed_at": processed_at.isoformat().replace("+00:00", "Z"),
        }
        for item in items:
            require(item["payload"] == expected, "Контракт webhook не совпадает с GET")

    async def wait_receipts(self, payment_id: str, count: int):
        async def probe():
            items = await self.receipts(payment_id)
            require(len(items) <= count, "Лишняя попытка webhook")
            return items if len(items) == count else None

        return await wait_for(probe, f"{count} webhook для {payment_id}")

    async def counts(self, payment_id: str, label: str, published: bool):
        async with async_session_maker() as session:
            payments = await session.scalar(
                select(func.count())
                .select_from(Payment)
                .where(Payment.idempotency_key == f"{self.run_id}-{label}")
            )
            outbox = list(
                (
                    await session.scalars(
                        select(Outbox).where(Outbox.payload["payment_id"].astext == payment_id)
                    )
                ).all()
            )
        require(payments == 1 and len(outbox) == 1, "Нужны один Payment и один Outbox")
        require((outbox[0].published_at is not None) == published, "Статус публикации Outbox")

    async def in_dlq(self, queue, payment_id: str):
        # Сообщения читаются без удаления: в конце все возвращаются в DLQ.
        await queue.declare()
        held = []
        found = False
        try:
            for _ in range(queue.declaration_result.message_count):
                message = await queue.get(fail=False, timeout=5)
                if message is None:
                    break
                held.append(message)
                try:
                    payload = json.loads(message.body)
                except ValueError, UnicodeError:
                    continue
                if isinstance(payload, dict) and payload.get("payment_id") == payment_id:
                    found = any(
                        item.get("reason") == "rejected"
                        for item in message.headers.get("x-death", [])
                    )
        finally:
            for message in held:
                await message.nack(requeue=True)
        return found

    async def payments(self):
        response = await self.client.post(
            self.api,
            headers={"X-API-Key": settings.api_key + "-invalid", "Idempotency-Key": self.run_id},
            json=self.body("ok"),
        )
        require(response.status_code == 401, "Неверный API-ключ должен возвращать 401")
        passed("Отсутствующий и неверный API-ключ отклоняются")

        payment = await self.create("success")
        payment_id = payment["payment_id"]
        items = await self.wait_receipts(payment_id, 1)
        saved = await self.get(payment_id)
        require(saved["status"] in {"succeeded", "failed"}, "Платёж не обработан")
        require(saved["processed_at"] is not None, "Дата обработки не сохранена")
        self.check_payload(saved, items)
        repeat = await self.create("success")
        require(repeat["payment_id"] == payment_id, "Повторный ключ создал другой платёж")
        require(repeat["created_at"] == payment["created_at"], "Изменилась дата создания")
        await asyncio.sleep(3)
        require(len(await self.receipts(payment_id)) == 1, "Повторный POST создал webhook")
        await self.counts(payment_id, "success", published=True)
        passed("POST → Outbox → RabbitMQ → webhook → GET; повторный ключ без дублей")

        responses = await asyncio.gather(*(self.create("concurrent") for _ in range(20)))
        ids = {item["payment_id"] for item in responses}
        require(len(ids) == 1, "Конкурентные запросы создали разные платежи")
        concurrent_id = ids.pop()
        await self.wait_receipts(concurrent_id, 1)
        await self.counts(concurrent_id, "concurrent", published=True)
        passed("20 конкурентных POST: один Payment и один Outbox")

        for mode, count in (("retry2", 2), ("retry3", 3)):
            payment_id = (await self.create(mode, mode))["payment_id"]
            items = await self.wait_receipts(payment_id, count)
            self.check_payload(await self.get(payment_id), items)
            self.check_intervals(items)
            await asyncio.sleep(3)
            require(len(await self.receipts(payment_id)) == count, "Лишний retry после успеха")
            passed(f"Успех webhook на попытке {count}")

        connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue("payments.dlq", passive=True)
            for mode in ("fail", "timeout", "unreachable"):
                payment_id = (await self.create(mode, mode))["payment_id"]

                async def completed():
                    payment = await self.get(payment_id)
                    return payment if payment["status"] != "pending" else None

                before = await wait_for(completed, "результат эмуляции")
                await wait_for(lambda: self.in_dlq(queue, payment_id), f"DLQ: {mode}")
                after = await self.get(payment_id)
                require(before["status"] == after["status"], "Ошибка webhook изменила статус")
                require(
                    before["processed_at"] == after["processed_at"], "Изменилась дата обработки"
                )
                if mode != "unreachable":
                    items = await self.receipts(payment_id)
                    require(len(items) == 3, "Ожидались три попытки")
                    self.check_payload(after, items)
                    self.check_intervals(items)
                passed(f"{mode}: DLQ с нужным UUID и reason=rejected, результат сохранён")

    @staticmethod
    def check_intervals(items):
        for index in range(len(items) - 1):
            interval = items[index + 1]["time"] - items[index]["time"]
            require(interval >= 2**index - 0.1, "Не соблюдена задержка retry")

    async def recovery_before(self):
        payment_id = (await self.create("recovery"))["payment_id"]
        await asyncio.sleep(3)
        require((await self.get(payment_id))["status"] == "pending", "Ожидался pending")
        require(not await self.receipts(payment_id), "Webhook пришёл при остановленном брокере")
        await self.counts(payment_id, "recovery", published=False)
        passed("RabbitMQ остановлен: POST 202, платёж pending, Outbox не опубликован")

    async def recovery_after(self):
        async with async_session_maker() as session:
            payment_id = await session.scalar(
                select(Payment.id).where(Payment.idempotency_key == f"{self.run_id}-recovery")
            )
        require(isinstance(payment_id, UUID), "Платёж для восстановления не найден")
        payment_id = str(payment_id)
        items = await self.wait_receipts(payment_id, 1)
        payment = await self.get(payment_id)
        self.check_payload(payment, items)
        await self.counts(payment_id, "recovery", published=True)
        passed("RabbitMQ восстановлен: автоматическая публикация и webhook без перезапуска workers")


async def main(mode: str):
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            check = DockerCheck(client)
            await check.ready()
            actions = {
                "payments": check.payments,
                "recovery-before": check.recovery_before,
                "recovery-after": check.recovery_after,
            }
            await actions[mode]()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "receiver":
        uvicorn.run(receiver, host="0.0.0.0", port=9000, access_log=False)
    else:
        asyncio.run(main(mode))
