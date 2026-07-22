import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from confluent_kafka import TopicPartition

from fastloom.signals.kafka.depends import KafkaSubscriber
from fastloom.signals.kafka.settings import KafkaSubscriptable


class _FakeRawConsumer:
    def __init__(self, fail_pause: bool = False, fail_resume: bool = False):
        self.paused: list[list[TopicPartition]] = []
        self.resumed: list[list[TopicPartition]] = []
        self._fail_pause = fail_pause
        self._fail_resume = fail_resume

    def pause(self, partitions: list[TopicPartition]) -> None:
        if self._fail_pause:
            raise RuntimeError("pause boom")
        self.paused.append(partitions)

    def resume(self, partitions: list[TopicPartition]) -> None:
        if self._fail_resume:
            raise RuntimeError("resume boom")
        self.resumed.append(partitions)


class _FakeConsumer:
    def __init__(self, fail_pause: bool = False, fail_resume: bool = False):
        self.consumer = _FakeRawConsumer(fail_pause, fail_resume)
        self._thread_pool = ThreadPoolExecutor(max_workers=1)


@pytest.fixture
def fake_consumer():
    consumer = _FakeConsumer()
    yield consumer
    consumer._thread_pool.shutdown()


def _fake_message(
    topic: str | None,
    partition: int | None,
    offset: int | None,
    is_manual: bool = True,
    batch_shape: type[list] | type[tuple] | None = None,
    key: bytes | None = b"k",
    consumer: _FakeConsumer | None = None,
):
    single = SimpleNamespace(
        topic=lambda: topic,
        partition=lambda: partition,
        offset=lambda: offset,
        key=lambda: key,
    )
    raw: (
        SimpleNamespace | list[SimpleNamespace] | tuple[SimpleNamespace, ...]
    ) = single if batch_shape is None else batch_shape([single])
    return SimpleNamespace(
        raw_message=raw, is_manual=is_manual, consumer=consumer
    )


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
    monkeypatch.setattr("random.uniform", lambda _lo, _hi: 0)
    return subscriber


def _middleware(subscriber):
    (factory,) = [
        m
        for m in subscriber.router.broker.middlewares
        if m.__name__ == "_RetryMiddleware"
    ]
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


async def test_ack_first_skips_backoff_but_still_raises_the_real_error(
    subscriber,
):
    await _fail(subscriber, is_manual=False)

    assert subscriber.slept == []  # never got to backoff


async def test_missing_partition_metadata_skips_backoff(subscriber):
    await _fail(subscriber, topic=None, partition=None, offset=None)

    assert subscriber.slept == []
    assert subscriber._retry_state == {}


@pytest.mark.parametrize("batch_shape", [list, tuple])
async def test_batch_message_backs_off_regardless_of_container_type(
    deterministic_subscriber, batch_shape
):
    # a batch is a tuple against a real broker but a list against
    # FastStream's own confluent test/mock broker - both must work.
    await _fail(deterministic_subscriber, batch_shape=batch_shape)

    assert deterministic_subscriber.slept == [1]


async def _drain_resumes(subscriber):
    while subscriber._pending_resumes:
        await asyncio.gather(*list(subscriber._pending_resumes))


async def test_keyed_message_never_touches_the_consumer(
    deterministic_subscriber, fake_consumer
):
    await _fail(deterministic_subscriber, key=b"k", consumer=fake_consumer)

    assert deterministic_subscriber.slept == [1]  # blocked inline, as before
    assert fake_consumer.consumer.paused == []
    assert fake_consumer.consumer.resumed == []


async def test_non_keyed_message_pauses_instead_of_blocking(
    deterministic_subscriber, fake_consumer
):
    await _fail(
        deterministic_subscriber, key=None, consumer=fake_consumer, offset=1
    )

    # backoff returns immediately - no inline sleep, no resume yet either
    assert deterministic_subscriber.slept == []
    assert fake_consumer.consumer.paused == [[TopicPartition("t", 0)]]
    assert fake_consumer.consumer.resumed == []

    await _drain_resumes(deterministic_subscriber)

    assert deterministic_subscriber.slept == [1]
    assert fake_consumer.consumer.resumed == [[TopicPartition("t", 0)]]


async def test_non_keyed_backoff_still_doubles_on_repeated_failures(
    deterministic_subscriber, fake_consumer
):
    for _ in range(4):
        await _fail(
            deterministic_subscriber,
            key=None,
            consumer=fake_consumer,
            offset=42,
        )
        await _drain_resumes(deterministic_subscriber)

    assert deterministic_subscriber.slept == [1, 2, 4, 8]
    assert len(fake_consumer.consumer.paused) == 4
    assert len(fake_consumer.consumer.resumed) == 4


async def test_pause_failure_falls_back_to_inline_backoff(
    deterministic_subscriber,
):
    fake_consumer = _FakeConsumer(fail_pause=True)

    await _fail(deterministic_subscriber, key=None, consumer=fake_consumer)

    # pause() blew up - the original ValueError still had to propagate,
    # and backoff must fall back to blocking instead of losing the retry
    assert deterministic_subscriber.slept == [1]
    assert fake_consumer.consumer.paused == []
    assert deterministic_subscriber._pending_resumes == set()

    fake_consumer._thread_pool.shutdown()


async def test_resume_failure_retries_then_gives_up(deterministic_subscriber):
    fake_consumer = _FakeConsumer(fail_resume=True)

    await _fail(deterministic_subscriber, key=None, consumer=fake_consumer)
    await _drain_resumes(deterministic_subscriber)

    # 1 initial backoff sleep + 2 retry sleeps between the 3 failed
    # resume attempts (base_delay=1 for every retry, not exponential)
    assert deterministic_subscriber.slept == [1, 1, 1]
    assert fake_consumer.consumer.paused == [[TopicPartition("t", 0)]]
    assert fake_consumer.consumer.resumed == []  # every attempt raised

    fake_consumer._thread_pool.shutdown()


async def test_enable_idempotence_forces_acks_all():
    settings = KafkaSubscriptable(
        ENVIRONMENT="test", PROJECT_NAME="p", KAFKA_URI="localhost:1"
    )
    try:
        sub = KafkaSubscriber(settings, acks=1, enable_idempotence=True)
        connection_config = (
            sub.router.broker.config.broker_config.connection_config
        )
        # -1 is librdkafka's resolved value for "all"
        assert connection_config.raw_producer_config["acks"] == -1
    finally:
        KafkaSubscriber.unbind()
