from collections.abc import Generator

import pytest
from testcontainers.core.wait_strategies import ExecWaitStrategy
from testcontainers.kafka import KafkaContainer

from fastloom.test.constants import (
    KAFKA_IMAGE,
    LOCALHOST_BASE_URL,
    MONGO_IMAGE,
    MONGO_PORT,
    POSTGRES_DB,
    POSTGRES_IMAGE,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    REDIS_IMAGE,
    REDIS_PORT,
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


@pytest.fixture(scope="session")
def redis_container() -> ContainerDataFixture:
    with create_container(
        REDIS_IMAGE,
        port=REDIS_PORT,
        wait_strategy=ExecWaitStrategy(["redis-cli", "ping"]),
    ) as (container, port_str):
        yield container, LOCALHOST_BASE_URL, port_str


@pytest.fixture(scope="session")
def postgres_container() -> ContainerDataFixture:
    with create_container(
        POSTGRES_IMAGE,
        port=POSTGRES_PORT,
        env_vars={
            "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
            "POSTGRES_DB": POSTGRES_DB,
        },
        wait_strategy=ExecWaitStrategy(["pg_isready", "-U", "postgres"]),
    ) as (container, port_str):
        yield container, LOCALHOST_BASE_URL, port_str
