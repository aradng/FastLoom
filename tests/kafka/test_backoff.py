from types import SimpleNamespace

import pytest

from fastloom.signals.kafka.depends import KafkaSubscriber
from fastloom.signals.kafka.settings import KafkaSubscriptable


def _fake_message(
    topic: str | None,
    partition: int | None,
    offset: int | None,
    is_manual: bool = True,
):
    raw = SimpleNamespace(
        topic=lambda: topic,
        partition=lambda: partition,
        offset=lambda: offset,
    )
    return SimpleNamespace(raw_message=raw, is_manual=is_manual)


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


@pytest.fixture
def deterministic_subscriber(subscriber, monkeypatch):
    monkeypatch.setattr("random.uniform", lambda _, cap: cap)
    return subscriber


def _middleware(subscriber):
    factory = subscriber.router.broker.middlewares[0]
    return factory(None, context=None)


async def _fail(subscriber, topic="t", partition=0, offset=0, **kwargs):
    async def raise_boom(_):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await _middleware(subscriber).consume_scope(
            raise_boom, _fake_message(topic, partition, offset, **kwargs)
        )


async def _succeed(subscriber, topic="t", partition=0, offset=0, **kwargs):
    async def ok(_):
        return "ok"

    await _middleware(subscriber).consume_scope(
        ok, _fake_message(topic, partition, offset, **kwargs)
    )


async def test_backoff_doubles_on_repeated_failures_of_same_offset(
    deterministic_subscriber,
):
    for _ in range(4):
        await _fail(deterministic_subscriber, offset=42)

    assert deterministic_subscriber.slept == [1, 2, 4, 8]  # capped at max=8


async def test_backoff_resets_on_a_new_offset(deterministic_subscriber):
    await _fail(deterministic_subscriber, offset=42)
    await _fail(deterministic_subscriber, offset=42)
    await _fail(deterministic_subscriber, offset=43)

    assert deterministic_subscriber.slept == [1, 2, 1]  # new offset -> reset


async def test_backoff_tracks_partitions_independently(
    deterministic_subscriber,
):
    await _fail(deterministic_subscriber, partition=0, offset=1)
    await _fail(deterministic_subscriber, partition=1, offset=1)

    assert deterministic_subscriber.slept == [1, 1]  # independent partitions


async def test_retry_state_cleared_on_matching_offset_success(
    deterministic_subscriber,
):
    await _fail(deterministic_subscriber, offset=1)
    assert ("t", 0) in deterministic_subscriber._retry_state

    await _succeed(deterministic_subscriber, offset=1)
    assert ("t", 0) not in deterministic_subscriber._retry_state


async def test_retry_state_not_clobbered_by_a_different_offsets_success(
    deterministic_subscriber,
):
    await _fail(deterministic_subscriber, offset=1)
    await _succeed(deterministic_subscriber, offset=2)  # different in-flight
    # offset succeeding shouldn't wipe offset 1's still-pending retry state
    assert deterministic_subscriber._retry_state[("t", 0)] == (1, 1)


async def test_backoff_applies_full_jitter(subscriber):
    for _ in range(4):
        await _fail(subscriber, offset=42)

    assert all(0 <= delay <= 8 for delay in subscriber.slept)
    assert len(set(subscriber.slept)) > 1  # not deterministic


async def test_ack_first_raises_instead_of_silently_no_op(subscriber):
    async def raise_boom(_):
        raise ValueError("boom")

    with pytest.raises(RuntimeError, match="ACK_FIRST"):
        await _middleware(subscriber).consume_scope(
            raise_boom, _fake_message("t", 0, 0, is_manual=False)
        )
    assert subscriber.slept == []  # never got to backoff


async def test_missing_partition_metadata_skips_backoff(subscriber):
    await _fail(subscriber, topic=None, partition=None, offset=None)

    assert subscriber.slept == []
    assert subscriber._retry_state == {}
