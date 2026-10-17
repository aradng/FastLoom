from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack

import pytest
from pydantic import BaseModel
from testcontainers.core.docker_client import DockerClient

from fastloom.test.constants import (
    LOCALHOST_BASE_URL,
    MONGO_IMAGE,
    POSTGRES_IMAGE,
)
from fastloom.test.container import PrivateRegistryDocker
from fastloom.test.fixtures.docker import mongo, postgres

_CONTAINERS_INI = "fastloom_shared_containers"
_WORKERINPUT_KEY = "fastloom_shared"


class SharedContainer(BaseModel):
    id: str
    host: str
    port: int


_STARTERS: dict[
    str,
    tuple[
        Callable[
            [str], AbstractContextManager[tuple[PrivateRegistryDocker, str]]
        ],
        str,
        str,
    ],
] = {
    "postgres": (postgres, "fastloom_postgres_image", POSTGRES_IMAGE),
    "mongo": (mongo, "fastloom_mongo_image", MONGO_IMAGE),
}

_STACK = pytest.StashKey[ExitStack]()
_SHARED = pytest.StashKey[dict[str, SharedContainer]]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        _CONTAINERS_INI,
        "containers started once per run and shared by every xdist worker: "
        + ", ".join(_STARTERS),
        type="linelist",
        default=[],
    )
    for _, image_ini, default in _STARTERS.values():
        parser.addini(
            image_ini, f"image for the shared {image_ini}", default=default
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if (
        hasattr(config, "workerinput")
        or config.option.collectonly
        or config.option.showfixtures
    ):
        return
    names = config.getini(_CONTAINERS_INI)
    if unknown := set(names) - set(_STARTERS):
        raise pytest.UsageError(
            f"{_CONTAINERS_INI}: unknown {sorted(unknown)}, "
            f"expected any of {sorted(_STARTERS)}"
        )
    stack = config.stash[_STACK] = ExitStack()
    shared = {}
    for name in names:
        start, image_ini, _ = _STARTERS[name]
        container, port = stack.enter_context(start(config.getini(image_ini)))
        shared[name] = SharedContainer(
            id=container.get_wrapped_container().id,
            host=LOCALHOST_BASE_URL,
            port=int(port),
        )
    config.stash[_SHARED] = shared


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node) -> None:
    node.workerinput[_WORKERINPUT_KEY] = {
        name: container.model_dump()
        for name, container in node.config.stash.get(_SHARED, {}).items()
    }


def pytest_unconfigure(config: pytest.Config) -> None:
    if _STACK in config.stash:
        config.stash[_STACK].close()


def _shared(config: pytest.Config, name: str) -> SharedContainer:
    if hasattr(config, "workerinput"):
        shared = {
            key: SharedContainer.model_validate(value)
            for key, value in config.workerinput[_WORKERINPUT_KEY].items()
        }
    else:
        shared = config.stash.get(_SHARED, {})
    if name not in shared:
        raise pytest.UsageError(
            f"add {name} to the {_CONTAINERS_INI} ini option"
        )
    return shared[name]


@pytest.fixture(scope="session")
def worker_database(worker_id: str) -> str:
    return f"test_{worker_id}"


@pytest.fixture(scope="session")
def shared_postgres(
    request: pytest.FixtureRequest, worker_database: str
) -> SharedContainer:
    container = _shared(request.config, "postgres")
    docker = DockerClient().client.containers.get(container.id)
    for command in (
        ["dropdb", "-U", "postgres", "--if-exists", worker_database],
        ["createdb", "-U", "postgres", worker_database],
    ):
        exit_code, output = docker.exec_run(command)
        assert exit_code == 0, output
    return container


@pytest.fixture(scope="session")
def shared_mongo(request: pytest.FixtureRequest) -> SharedContainer:
    return _shared(request.config, "mongo")
