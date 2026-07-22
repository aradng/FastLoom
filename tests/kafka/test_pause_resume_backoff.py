import asyncio
from typing import cast

from confluent_kafka import Message
from confluent_kafka.admin import AdminClient, NewTopic
from faststream.confluent.fastapi import KafkaMessage

TOPIC = "pause-resume-backoff-test"


async def test_non_keyed_backoff_does_not_block_other_partitions(
    kafka_subscriber, kafka_container
):
    admin = AdminClient(
        {"bootstrap.servers": kafka_container.get_bootstrap_server()}
    )
    admin.create_topics(
        [NewTopic(TOPIC, num_partitions=2, replication_factor=1)]
    )
    await asyncio.sleep(2)  # topic metadata propagation

    router = kafka_subscriber.router
    failed_event = asyncio.Event()
    partition_1_done = asyncio.Event()
    times: dict[str, float] = {}

    @router.subscriber(
        TOPIC,
        group_id="pause-resume-backoff-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: KafkaMessage) -> None:
        raw = cast(Message, msg.raw_message)
        if raw.partition() == 0 and not failed_event.is_set():
            times["failed_at"] = asyncio.get_event_loop().time()
            failed_event.set()
            raise ValueError("boom - forces partition 0 into backoff")
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
    finally:
        await router.broker.stop()

    elapsed = times["partition_1_at"] - times["failed_at"]
    # kafka_subscriber's default base_delay is 5s - partition 1 arriving
    # well under that, right after partition 0 failed, proves the fetch
    # loop kept polling instead of blocking on partition 0's backoff.
    assert elapsed < 4
