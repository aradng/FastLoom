from collections.abc import Generator
from contextlib import AbstractContextManager

import pytest
from testcontainers.core.wait_strategies import ExecWaitStrategy
from testcontainers.kafka import KafkaContainer

from fastloom.test.constants import (
    KAFKA_IMAGE,
    LOCALHOST_BASE_URL,
    MONGO_IMAGE,
    MONGO_PORT,
    POLL_INTERVAL,
    POSTGRES_DB,
    POSTGRES_IMAGE,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    REDIS_IMAGE,
    REDIS_PORT,
)
from fastloom.test.container import PrivateRegistryDocker, create_container
from fastloom.test.types import ContainerDataFixture


def postgres() -> AbstractContextManager[tuple[PrivateRegistryDocker, str]]:
    return create_container(
        POSTGRES_IMAGE,
        port=POSTGRES_PORT,
        env_vars={
            "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
            "POSTGRES_DB": POSTGRES_DB,
            "POSTGRES_HOST_AUTH_METHOD": "trust",
        },
        commands=(
            "-c fsync=off -c synchronous_commit=off -c full_page_writes=off"
            " -c max_connections=500"
        ),
        tmpfs={"/var/lib/postgresql": "rw"},
        host_ip="127.0.0.1",
        wait_strategy=ExecWaitStrategy(
            ["pg_isready", "-h", "127.0.0.1", "-U", "postgres"]
        ).with_poll_interval(POLL_INTERVAL),
    )


def mongo() -> AbstractContextManager[tuple[PrivateRegistryDocker, str]]:
    return create_container(MONGO_IMAGE, port=MONGO_PORT)


@pytest.fixture(scope="session")
def mongo_container() -> ContainerDataFixture:
    with mongo() as (container, port_str):
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
        wait_strategy=ExecWaitStrategy(
            ["redis-cli", "ping"]
        ).with_poll_interval(POLL_INTERVAL),
    ) as (container, port_str):
        yield container, LOCALHOST_BASE_URL, port_str


@pytest.fixture(scope="session")
def postgres_container() -> ContainerDataFixture:
    with postgres() as (container, port_str):
        yield container, LOCALHOST_BASE_URL, port_str
