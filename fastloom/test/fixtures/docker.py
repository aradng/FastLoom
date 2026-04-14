import pytest

from fastloom.test.constants import LOCALHOST_BASE_URL, MONGO_IMAGE, MONGO_PORT
from fastloom.test.container import create_container
from fastloom.test.types import ContainerDataFixture


@pytest.fixture(scope="session")
def mongo_container() -> ContainerDataFixture:
    with create_container(MONGO_IMAGE, port=MONGO_PORT) as (
        container,
        port_str,
    ):
        yield container, LOCALHOST_BASE_URL, port_str
