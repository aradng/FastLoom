from types import SimpleNamespace

import pytest

from fastloom.signals.rabbit.depends import (
    RabbitSubscriber,
    RabbitSubscriptable,
)


def _fake_message(routing_key: str, delivery_count: int = 0):
    headers = {"x-delivery-count": delivery_count} if delivery_count else {}
    return SimpleNamespace(
        headers=headers,
        body=b"payload",
        raw_message=SimpleNamespace(routing_key=routing_key),
    )


@pytest.fixture
def subscriber(monkeypatch):
    published: list[dict] = []

    async def fake_get_ensured_dlx_queue(cls, routing_key, delay):
        return SimpleNamespace(name=f"{routing_key}.{delay}")

    async def fake_publish(message, **kwargs):
        published.append({"expiration": message.expiration, **kwargs})

    monkeypatch.setattr(
        RabbitSubscriber,
        "_get_ensured_dlx_queue",
        classmethod(fake_get_ensured_dlx_queue),
    )

    settings = RabbitSubscriptable(
        ENVIRONMENT="test", PROJECT_NAME="p", RABBIT_URI="amqp://localhost"
    )
    sub = RabbitSubscriber(settings, base_delay=1, max_delay=8)
    monkeypatch.setattr(sub.router.broker, "publish", fake_publish)
    sub.published = published  # type: ignore[attr-defined]
    yield sub
    RabbitSubscriber.unbind()


async def _fail(subscriber, routing_key="foo", delivery_count=0):
    message = _fake_message(routing_key, delivery_count)
    with pytest.raises(ValueError):
        await subscriber._exc_handler(ValueError("boom"), message)


async def test_expiration_reflects_the_backoff_delay(subscriber, monkeypatch):
    monkeypatch.setattr("random.uniform", lambda _lo, _hi: 0)
    await _fail(subscriber, delivery_count=3)  # attempt 4 -> delay = 8 (cap)

    assert subscriber.published[-1]["expiration"] == 8
