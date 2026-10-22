import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aio_pika import DeliveryMode, Message
from faststream.exceptions import RejectMessage
from pamqp.commands import Basic

from app.consumers import payment_consumer as consumer
from app.db.models.payment import PaymentStatus
from app.messaging.broker import payments_dlq, payments_queue
from app.messaging.rabbitmq import RabbitMQ
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate
from app.services.payment_service import PaymentService
from app.workers import outbox_publisher

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("scenario", ["new", "repeat", "conflict"])
async def test_payment_creation_and_outbox(payment, payment_payload, scenario):
    repository = SimpleNamespace(
        get_by_idempotency_key=AsyncMock(
            side_effect=[payment] if scenario == "repeat" else [None, payment]
        ),
        create_if_absent=AsyncMock(return_value=None if scenario == "conflict" else payment),
    )
    outbox = SimpleNamespace(create=AsyncMock())
    service = PaymentService(repository, outbox)

    result = await service.create_payment(PaymentCreate(**payment_payload), payment.idempotency_key)

    assert result is payment
    if scenario == "new":
        repository.create_if_absent.assert_awaited_once()
        candidate = repository.create_if_absent.await_args.args[0]
        assert candidate.amount == payment.amount
        assert candidate.idempotency_key == payment.idempotency_key
        outbox.create.assert_awaited_once()
        event = outbox.create.await_args.args[0]
        assert event.event_type == "payments.new"
        assert event.payload == {"payment_id": str(payment.id)}
    else:
        outbox.create.assert_not_awaited()
        if scenario == "repeat":
            repository.create_if_absent.assert_not_awaited()
        else:
            repository.create_if_absent.assert_awaited_once()
            assert repository.get_by_idempotency_key.await_count == 2


@pytest.mark.parametrize("publication_fails", [False, True])
async def test_outbox_is_marked_only_after_success(monkeypatch, payment, publication_fails):
    event = SimpleNamespace(
        id=payment.id, event_type="payments.new", payload={"payment_id": str(payment.id)}
    )
    repository = SimpleNamespace(
        get_unpublished=AsyncMock(return_value=[event]),
        mark_as_published=AsyncMock(),
    )
    monkeypatch.setattr(outbox_publisher, "OutboxRepository", lambda session: repository)

    async def publish(message, routing_key):
        repository.mark_as_published.assert_not_awaited()
        assert routing_key == "payments.new"
        assert json.loads(message.body) == event.payload
        assert message.delivery_mode == DeliveryMode.PERSISTENT
        if publication_fails:
            raise ConnectionError("Broker unavailable")

    rabbitmq = SimpleNamespace(publish=AsyncMock(side_effect=publish))
    publisher = outbox_publisher.OutboxPublisher(session=None, rabbitmq=rabbitmq)
    if publication_fails:
        with pytest.raises(ConnectionError):
            await publisher.publish_once()
        repository.mark_as_published.assert_not_awaited()
    else:
        await publisher.publish_once()
        repository.mark_as_published.assert_awaited_once_with(event.id)
    rabbitmq.publish.assert_awaited_once()


@pytest.fixture
def consumer_dependencies(monkeypatch, payment):
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(consumer, "async_session_maker", lambda: session)

    async def update_status(target, status):
        target.status = status
        target.processed_at = target.created_at

    repository = SimpleNamespace(
        get_by_id_for_update=AsyncMock(return_value=payment),
        update_status=AsyncMock(side_effect=update_status),
    )
    monkeypatch.setattr(consumer, "PaymentRepository", lambda session: repository)
    sleep = AsyncMock()
    monkeypatch.setattr(consumer.asyncio, "sleep", sleep)
    monkeypatch.setattr(consumer.random, "uniform", lambda low, high: 3.0)

    client = AsyncMock()
    client.__aenter__.return_value = client
    # Build the response before replacing AsyncClient.
    response = httpx.Response(200, request=httpx.Request("POST", payment.webhook_url))

    async def post(url, json):
        session.commit.assert_awaited_once()
        assert url == payment.webhook_url
        assert json == {
            "payment_id": str(payment.id),
            "status": payment.status.value,
            "amount": "100.00",
            "currency": "RUB",
            "processed_at": "2026-10-12T09:33:11Z",
        }
        return response

    client.post.side_effect = post
    monkeypatch.setattr(consumer.httpx, "AsyncClient", lambda **kwargs: client)
    message = SimpleNamespace(body=json.dumps({"payment_id": str(payment.id)}).encode())
    return SimpleNamespace(
        session=session, repository=repository, sleep=sleep, client=client, message=message
    )


@pytest.mark.parametrize(
    ("random_value", "expected_status"),
    [(0.5, PaymentStatus.SUCCEEDED), (0.95, PaymentStatus.FAILED)],
)
async def test_pending_payment_is_saved_before_webhook(
    monkeypatch, payment, consumer_dependencies, random_value, expected_status
):
    dependencies = consumer_dependencies
    payment.status = PaymentStatus.PENDING
    monkeypatch.setattr(consumer.random, "random", lambda: random_value)

    await consumer.process_payment(dependencies.message)

    dependencies.repository.get_by_id_for_update.assert_awaited_once_with(str(payment.id))
    dependencies.repository.update_status.assert_awaited_once_with(payment, expected_status)
    assert payment.processed_at is not None
    dependencies.sleep.assert_awaited_once_with(3.0)
    dependencies.client.post.assert_awaited_once()


@pytest.mark.parametrize("failures", [0, 1, 2, 3])
async def test_completed_payment_webhook_retry_and_rejection(
    payment, consumer_dependencies, failures
):
    dependencies = consumer_dependencies
    payment.status = PaymentStatus.SUCCEEDED
    payment.processed_at = payment.created_at
    original_processed_at = payment.processed_at
    successful_post = dependencies.client.post.side_effect
    attempts = 0

    async def post(url, json):
        nonlocal attempts
        attempts += 1
        response = await successful_post(url, json)
        if attempts <= failures:
            return httpx.Response(500, request=response.request)
        return response

    dependencies.client.post.side_effect = post
    if failures == 3:
        with pytest.raises(RejectMessage) as error:
            await consumer.process_payment(dependencies.message)
        assert error.value.extra_options == {"requeue": False}
        assert payments_queue.arguments["x-dead-letter-exchange"] == ""
        assert payments_queue.arguments["x-dead-letter-routing-key"] == payments_dlq.name
        assert payments_dlq.durable is True
    else:
        await consumer.process_payment(dependencies.message)

    assert attempts == min(failures + 1, 3)
    assert [call.args[0] for call in dependencies.sleep.await_args_list] == [1, 2][
        : min(failures, 2)
    ]
    dependencies.repository.update_status.assert_not_awaited()
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.processed_at == original_processed_at


@pytest.mark.parametrize("confirmed", [True, False])
async def test_publication_requires_broker_ack(confirmed):
    rabbitmq = RabbitMQ()
    publish = AsyncMock(return_value=Basic.Ack() if confirmed else Basic.Nack())
    rabbitmq.channel = SimpleNamespace(default_exchange=SimpleNamespace(publish=publish))
    message = Message(body=b"test")

    if confirmed:
        await rabbitmq.publish(message, "payments.new")
    else:
        with pytest.raises(RuntimeError, match="did not confirm"):
            await rabbitmq.publish(message, "payments.new")

    publish.assert_awaited_once_with(
        message, routing_key="payments.new", mandatory=True, timeout=10
    )


async def test_payment_processing_time_is_utc(payment):
    session = AsyncMock()
    repository = PaymentRepository(session)
    before = datetime.now(UTC)

    await repository.update_status(payment, PaymentStatus.SUCCEEDED)

    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.processed_at.tzinfo is UTC
    assert before <= payment.processed_at <= datetime.now(UTC)
    session.flush.assert_awaited_once()
