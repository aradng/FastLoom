from collections.abc import Generator

import pytest
from testcontainers.kafka import KafkaContainer

from fastloom.test.constants import (
    KAFKA_IMAGE,
    LOCALHOST_BASE_URL,
    MONGO_IMAGE,
    MONGO_PORT,
)
from fastloom.test.container import create_container
from fastloom.test.types import ContainerDataFixture


@pytest.fixture(scope="session")
def mongo_container() -> ContainerDataFixture:
    with create_container(MONGO_IMAGE, port=MONGO_PORT) as (
        container,
        port_str,
    ):
        yield container, LOCALHOST_BASE_URL, port_str


@pytest.fixture(scope="session")
def kafka_container() -> Generator[KafkaContainer]:
    container = KafkaContainer(image=KAFKA_IMAGE)
    # with_kraft() parses the tag as a semver to gate on MIN_KRAFT_TAG,
    # which chokes on "latest" — set the flag it would set directly.
    container.kraft_enabled = True
    with container:
        yield container
