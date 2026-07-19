import asyncio
import json

from pydantic import BaseModel


class _Quote(BaseModel):
    symbol: str
    exchange: str
    price: float


async def test_json_body_with_unrecognized_content_type_still_parses(
    kafka_subscriber,
):
    # a producer outside the faststream/fastloom ecosystem (or one that
    # tags a foreign/incorrect content-type) leaves body decoding to raw
    # bytes even though the payload is valid JSON matching the handler's
    # model - regression for the RequestValidationError this used to
    # raise (fields reported missing, with the whole undecoded payload
    # showing up wrapped under the handler's own param name).
    router = kafka_subscriber.router
    received: list[_Quote] = []
    done = asyncio.Event()

    @router.subscriber(
        "foreign-producer-test-topic",
        group_id="foreign-producer-test",
        auto_offset_reset="earliest",
    )
    async def handler(signal_in: _Quote) -> None:
        received.append(signal_in)
        done.set()

    publisher = router.publisher("foreign-producer-test-topic")
    payload = json.dumps(
        {"symbol": "LONDONGAS", "exchange": "IG", "price": 1151.3}
    ).encode()

    await router.broker.start()
    try:
        await publisher.publish(
            payload,
            headers={"content-type": "application/octet-stream"},
        )
        await asyncio.wait_for(done.wait(), timeout=15)
    finally:
        await router.broker.stop()

    assert received == [
        _Quote(symbol="LONDONGAS", exchange="IG", price=1151.3)
    ]
