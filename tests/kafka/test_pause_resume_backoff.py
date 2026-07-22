import asyncio

from confluent_kafka import KafkaError, KafkaException, Message
from confluent_kafka.admin import AdminClient, NewTopic
from faststream.confluent.fastapi import KafkaMessage

TOPIC = "pause-resume-backoff-test"


def _create_topic(admin: AdminClient) -> None:
    (future,) = admin.create_topics(
        [NewTopic(TOPIC, num_partitions=2, replication_factor=1)]
    ).values()
    try:
        future.result()
    except KafkaException as e:
        if e.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise


async def _wait_for_topic(admin: AdminClient, partitions: int) -> None:
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        metadata = admin.list_topics(topic=TOPIC, timeout=2).topics.get(TOPIC)
        if metadata is not None and len(metadata.partitions) == partitions:
            return
        await asyncio.sleep(0.2)
    raise TimeoutError(f"topic {TOPIC} never reached {partitions} partitions")


async def test_non_keyed_backoff_does_not_block_other_partitions(
    kafka_subscriber, kafka_container
):
    admin = AdminClient(
        {"bootstrap.servers": kafka_container.get_bootstrap_server()}
    )
    _create_topic(admin)
    await _wait_for_topic(admin, partitions=2)

    router = kafka_subscriber.router
    failed_event = asyncio.Event()
    partition_1_done = asyncio.Event()
    partition_0_recovered = asyncio.Event()
    times: dict[str, float] = {}

    @router.subscriber(
        TOPIC,
        group_id="pause-resume-backoff-test",
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

    publisher = router.publisher(TOPIC)
    await router.broker.start()
    try:
        # no key on either publish - non-keyed, the case this backoff
        # design applies to (see docs/adr/01-kafka-non-keyed-retry-backoff)
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
