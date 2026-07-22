import asyncio

from confluent_kafka import KafkaError, KafkaException, Message
from confluent_kafka.admin import AdminClient, NewTopic
from faststream.confluent.fastapi import KafkaMessage

from fastloom.signals.kafka.depends import KafkaSubscriber
from fastloom.signals.kafka.settings import KafkaSubscriptable


class _ConsumerProxy:
    """Forwards to the real confluent Consumer, recording pause()/resume()
    calls and optionally forcing one of them to fail - keeps the rest of
    the stack (broker, thread pool, message flow) real."""

    def __init__(self, real, *, fail_pause=False, fail_resume=False):
        self._real = real
        self._fail_pause = fail_pause
        self._fail_resume = fail_resume
        self.pause_attempts = 0
        self.resume_attempts = 0

    def pause(self, partitions):
        self.pause_attempts += 1
        if self._fail_pause:
            raise RuntimeError("pause boom")
        return self._real.pause(partitions)

    def resume(self, partitions):
        self.resume_attempts += 1
        if self._fail_resume:
            raise RuntimeError("resume boom")
        return self._real.resume(partitions)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _create_topic(admin: AdminClient, topic: str, num_partitions: int) -> None:
    (future,) = admin.create_topics(
        [NewTopic(topic, num_partitions=num_partitions, replication_factor=1)]
    ).values()
    try:
        future.result()
    except KafkaException as e:
        if e.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise


async def _wait_for_topic(
    admin: AdminClient, topic: str, partitions: int
) -> None:
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        metadata = admin.list_topics(topic=topic, timeout=2).topics.get(topic)
        if metadata is not None and len(metadata.partitions) >= partitions:
            return
        await asyncio.sleep(0.2)
    raise TimeoutError(f"topic {topic} never reached {partitions} partitions")


async def _wait_until(predicate, timeout: float = 15) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("condition never became true")


async def test_non_keyed_backoff_does_not_block_other_partitions(
    kafka_subscriber, kafka_container
):
    topic = "cross-partition-test"
    admin = AdminClient(
        {"bootstrap.servers": kafka_container.get_bootstrap_server()}
    )
    _create_topic(admin, topic, num_partitions=2)
    await _wait_for_topic(admin, topic, partitions=2)

    router = kafka_subscriber.router
    failed_event = asyncio.Event()
    partition_1_done = asyncio.Event()
    partition_0_recovered = asyncio.Event()
    times: dict[str, float] = {}

    @router.subscriber(
        topic,
        group_id="cross-partition-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: KafkaMessage) -> None:
        raw = msg.raw_message
        assert isinstance(raw, Message)
        if raw.partition() == 0:
            if not failed_event.is_set():
                times["failed_at"] = asyncio.get_event_loop().time()
                failed_event.set()
                raise ValueError("boom - forces partition 0 into backoff")
            partition_0_recovered.set()
        if raw.partition() == 1:
            times["partition_1_at"] = asyncio.get_event_loop().time()
            partition_1_done.set()

    publisher = router.publisher(topic)
    await router.broker.start()
    try:
        # no key on either publish - non-keyed, the case this backoff
        # design applies to (see docs/adr/01-kafka-retry-backoff)
        await publisher.publish("p0-msg", partition=0)
        # only publish partition 1's message once partition 0 has
        # actually failed and entered backoff - guarantees the ordering
        # this test depends on instead of racing two publishes at once
        await asyncio.wait_for(failed_event.wait(), timeout=15)

        await publisher.publish("p1-msg", partition=1)
        await asyncio.wait_for(partition_1_done.wait(), timeout=15)

        # partition 0's original message must still get redelivered and
        # succeed once the backoff's resume() fires - proves the pause
        # is temporary, not a permanent stall of that partition
        await asyncio.wait_for(partition_0_recovered.wait(), timeout=15)
    finally:
        await router.broker.stop()

    elapsed = times["partition_1_at"] - times["failed_at"]
    # kafka_subscriber's default base_delay is 5s - partition 1 arriving
    # well under that, right after partition 0 failed, proves the fetch
    # loop kept polling instead of blocking on partition 0's backoff.
    assert elapsed < 4


async def test_keyed_message_never_touches_the_consumer(kafka_container):
    topic = "keyed-never-touches-test"
    admin = AdminClient(
        {"bootstrap.servers": kafka_container.get_bootstrap_server()}
    )
    _create_topic(admin, topic, num_partitions=1)
    await _wait_for_topic(admin, topic, partitions=1)

    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
    )
    subscriber = KafkaSubscriber(settings, base_delay=1, max_delay=8)
    proxy: _ConsumerProxy | None = None
    failed_event = asyncio.Event()

    @subscriber.router.subscriber(
        topic,
        group_id="keyed-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: KafkaMessage) -> None:
        nonlocal proxy
        if proxy is None:
            proxy = _ConsumerProxy(msg.consumer.consumer)
            msg.consumer.consumer = proxy
        if not failed_event.is_set():
            failed_event.set()
            raise ValueError("boom")

    publisher = subscriber.router.publisher(topic)
    await subscriber.router.broker.start()
    try:
        await publisher.publish("keyed-msg", key=b"some-key")
        await asyncio.wait_for(failed_event.wait(), timeout=15)
        # give the (keyed -> inline sleep) path a moment - long enough to
        # prove it never reaches for pause/resume at all
        await asyncio.sleep(1)
    finally:
        await subscriber.router.broker.stop()
        KafkaSubscriber.unbind()

    assert proxy is not None
    assert proxy.pause_attempts == 0
    assert proxy.resume_attempts == 0


async def test_non_keyed_message_pauses_then_resumes(kafka_container):
    topic = "non-keyed-pauses-then-resumes-test"
    admin = AdminClient(
        {"bootstrap.servers": kafka_container.get_bootstrap_server()}
    )
    _create_topic(admin, topic, num_partitions=1)
    await _wait_for_topic(admin, topic, partitions=1)

    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
    )
    subscriber = KafkaSubscriber(settings, base_delay=1, max_delay=8)
    proxy: _ConsumerProxy | None = None
    failed_event = asyncio.Event()
    recovered_event = asyncio.Event()

    @subscriber.router.subscriber(
        topic,
        group_id="non-keyed-pause-resume-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: KafkaMessage) -> None:
        nonlocal proxy
        if proxy is None:
            proxy = _ConsumerProxy(msg.consumer.consumer)
            msg.consumer.consumer = proxy
        if not failed_event.is_set():
            failed_event.set()
            raise ValueError("boom")
        recovered_event.set()

    publisher = subscriber.router.publisher(topic)
    await subscriber.router.broker.start()
    try:
        await publisher.publish("non-keyed-msg")  # no key
        await asyncio.wait_for(failed_event.wait(), timeout=15)
        await asyncio.wait_for(recovered_event.wait(), timeout=15)
    finally:
        await subscriber.router.broker.stop()
        KafkaSubscriber.unbind()

    assert proxy is not None
    assert proxy.pause_attempts == 1
    assert proxy.resume_attempts == 1


async def test_pause_failure_falls_back_to_inline_backoff(kafka_container):
    topic = "pause-failure-test"
    admin = AdminClient(
        {"bootstrap.servers": kafka_container.get_bootstrap_server()}
    )
    _create_topic(admin, topic, num_partitions=1)
    await _wait_for_topic(admin, topic, partitions=1)

    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
    )
    subscriber = KafkaSubscriber(settings, base_delay=1, max_delay=8)
    proxy: _ConsumerProxy | None = None
    failed_event = asyncio.Event()
    recovered_event = asyncio.Event()

    @subscriber.router.subscriber(
        topic,
        group_id="pause-failure-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: KafkaMessage) -> None:
        nonlocal proxy
        if proxy is None:
            proxy = _ConsumerProxy(msg.consumer.consumer, fail_pause=True)
            msg.consumer.consumer = proxy
        if not failed_event.is_set():
            failed_event.set()
            raise ValueError("boom")
        recovered_event.set()

    publisher = subscriber.router.publisher(topic)
    await subscriber.router.broker.start()
    try:
        await publisher.publish("pause-failure-msg")  # no key
        await asyncio.wait_for(failed_event.wait(), timeout=15)
        # pause() raised - the original exception still had to propagate
        # for redelivery instead of being swallowed, so the message must
        # come back and succeed via the inline-sleep fallback
        await asyncio.wait_for(recovered_event.wait(), timeout=15)
    finally:
        await subscriber.router.broker.stop()
        KafkaSubscriber.unbind()

    assert proxy is not None
    assert proxy.pause_attempts == 1
    assert proxy.resume_attempts == 0  # never scheduled - pause failed first


async def test_resume_failure_retries_then_gives_up(kafka_container, caplog):
    topic = "resume-failure-test"
    admin = AdminClient(
        {"bootstrap.servers": kafka_container.get_bootstrap_server()}
    )
    _create_topic(admin, topic, num_partitions=1)
    await _wait_for_topic(admin, topic, partitions=1)

    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
    )
    subscriber = KafkaSubscriber(settings, base_delay=1, max_delay=8)
    proxy: _ConsumerProxy | None = None
    failed_event = asyncio.Event()

    @subscriber.router.subscriber(
        topic,
        group_id="resume-failure-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: KafkaMessage) -> None:
        nonlocal proxy
        if proxy is None:
            proxy = _ConsumerProxy(msg.consumer.consumer, fail_resume=True)
            msg.consumer.consumer = proxy
        if not failed_event.is_set():
            failed_event.set()
            raise ValueError("boom")

    publisher = subscriber.router.publisher(topic)
    await subscriber.router.broker.start()
    try:
        await publisher.publish("resume-failure-msg")  # no key
        await asyncio.wait_for(failed_event.wait(), timeout=15)
        await _wait_until(
            lambda: proxy is not None and proxy.resume_attempts >= 3
        )
    finally:
        await subscriber.router.broker.stop()
        KafkaSubscriber.unbind()

    assert proxy is not None
    assert proxy.pause_attempts == 1
    assert proxy.resume_attempts == 3  # retried 3x, every attempt raised
    assert "giving up resuming" in caplog.text
