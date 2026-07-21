from types import SimpleNamespace

import pytest

from fastloom.signals.kafka.depends import KafkaSubscriber
from fastloom.signals.kafka.settings import KafkaSubscriptable


def _fake_message(topic: str, partition: int, offset: int):
    raw = SimpleNamespace(
        topic=lambda: topic,
        partition=lambda: partition,
        offset=lambda: offset,
    )
    return SimpleNamespace(raw_message=raw)


@pytest.fixture
def subscriber(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    settings = KafkaSubscriptable(
        ENVIRONMENT="test", PROJECT_NAME="p", KAFKA_URI="localhost:1"
    )
    sub = KafkaSubscriber(settings, base_delay=1, max_delay=8)
    sub.slept = slept  # type: ignore[attr-defined]
    yield sub
    KafkaSubscriber.unbind()


def _middleware(subscriber):
    factory = subscriber.router.broker.middlewares[0]
    return factory(None, context=None)


async def _fail(subscriber, topic="t", partition=0, offset=0):
    async def raise_boom(_):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await _middleware(subscriber).consume_scope(
            raise_boom, _fake_message(topic, partition, offset)
        )


async def _succeed(subscriber, topic="t", partition=0, offset=0):
    async def ok(_):
        return "ok"

    await _middleware(subscriber).consume_scope(
        ok, _fake_message(topic, partition, offset)
    )


async def test_backoff_doubles_on_repeated_failures_of_same_offset(
    subscriber,
):
    for _ in range(4):
        await _fail(subscriber, offset=42)

    assert subscriber.slept == [1, 2, 4, 8]  # capped at max_delay=8


async def test_backoff_resets_on_a_new_offset(subscriber):
    await _fail(subscriber, offset=42)
    await _fail(subscriber, offset=42)
    await _fail(subscriber, offset=43)

    assert subscriber.slept == [1, 2, 1]  # new offset -> back to attempt 1


async def test_backoff_tracks_partitions_independently(subscriber):
    await _fail(subscriber, partition=0, offset=1)
    await _fail(subscriber, partition=1, offset=1)

    assert subscriber.slept == [1, 1]  # different partitions, both attempt 1


async def test_retry_state_cleared_on_success(subscriber):
    await _fail(subscriber, offset=1)
    assert ("t", 0) in subscriber._retry_state

    await _succeed(subscriber, offset=2)
    assert ("t", 0) not in subscriber._retry_state
