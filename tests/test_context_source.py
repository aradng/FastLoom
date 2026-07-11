from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from faststream.confluent import TestKafkaBroker
from faststream.confluent.fastapi import KafkaRouter
from faststream.message.source_type import SourceType
from faststream.rabbit import TestRabbitBroker
from faststream.rabbit.fastapi import RabbitRouter
from faststream.rabbit.message import RabbitMessage
from faststream.rabbit.parser import AioPikaParser

from fastloom.tenant.depends import ContextSource


async def test_context_source_extracts_tenant_from_message_body():
    message = RabbitMessage(
        raw_message=None,
        body=b'{"tenant": "acme", "foo": "bar"}',
        headers={"content-type": "application/json"},
        content_type="application/json",
        source_type=SourceType.CONSUME,
    )
    message.set_decoder(AioPikaParser().decode_message)

    tenant = await ContextSource(settings={}, general=None)._dep(message)

    assert tenant == "acme"


@pytest.mark.parametrize(
    ("router_cls", "test_broker_cls", "uri"),
    [
        (RabbitRouter, TestRabbitBroker, "amqp://guest:guest@localhost:5672/"),
        (KafkaRouter, TestKafkaBroker, "localhost:9092"),
    ],
)
async def test_context_source_resolves_tenant_end_to_end(
    router_cls, test_broker_cls, uri
):
    router = router_cls(uri)
    dep_fn = ContextSource(settings={"acme": object()}, general=None).get_dep()
    received = {}

    @router.subscriber("probe")
    async def handler(tenant: Annotated[str | None, Depends(dep_fn)] = None):
        received["tenant"] = tenant

    async with test_broker_cls(router.broker) as br:
        await br.publish({"tenant": "acme", "foo": "bar"}, "probe")

    assert received["tenant"] == "acme"


def _mock_broker(router):
    router.broker.start = AsyncMock()
    router.broker.stop = AsyncMock()
    return router


@pytest.mark.parametrize(
    ("router_cls", "uri", "schema_path"),
    [
        (RabbitRouter, "amqp://guest:guest@localhost:5672/", "/api/rabbitapi"),
        (KafkaRouter, "localhost:9092", "/api/kafkaapi"),
    ],
)
def test_context_source_asyncapi_schema_generation(
    router_cls, uri, schema_path
):
    router = _mock_broker(router_cls(uri, schema_url=schema_path))
    dep_fn = ContextSource(settings={}, general=None).get_dep()

    @router.subscriber("probe")
    async def handler(tenant: Annotated[str | None, Depends(dep_fn)] = None):
        pass

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        resp = client.get(f"{schema_path}.json")

    assert resp.status_code == 200
