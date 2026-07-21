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


async def _fail(subscriber, topic="t", partition=0, offset=0):
    with pytest.raises(ValueError):
        await subscriber._exc_handler(
            ValueError("boom"), _fake_message(topic, partition, offset)
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
