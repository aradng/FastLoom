from contextlib import ExitStack, closing
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel
from testcontainers.core.docker_client import DockerClient

from fastloom.test.constants import LOCALHOST_BASE_URL
from fastloom.test.fixtures.docker import mongo, postgres

if TYPE_CHECKING:
    from xdist.workermanage import WorkerController

_CONTAINERS_INI = "fastloom_shared_containers"
_WORKERINPUT_KEY = "fastloom_shared"
_STARTERS = {"postgres": postgres, "mongo": mongo}


class SharedContainer(BaseModel):
    id: str
    port: int
    host: str = LOCALHOST_BASE_URL


_SHARED = pytest.StashKey[dict[str, SharedContainer]]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        _CONTAINERS_INI,
        "containers started once per run and shared by every xdist worker: "
        + ", ".join(_STARTERS),
        type="linelist",
        default=[],
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if hasattr(config, "workerinput") or any(
        getattr(config.option, flag, False)
        for flag in (
            "collectonly",
            "showfixtures",
            "show_fixtures_per_test",
            "setupplan",
        )
    ):
        return
    names = config.getini(_CONTAINERS_INI)
    if unknown := set(names) - set(_STARTERS):
        raise pytest.UsageError(
            f"{_CONTAINERS_INI}: unknown {sorted(unknown)}, "
            f"expected any of {sorted(_STARTERS)}"
        )
    stack = ExitStack()
    config.add_cleanup(stack.close)
    shared = {}
    for name in names:
        container, port = stack.enter_context(_STARTERS[name]())
        shared[name] = SharedContainer(
            id=container.get_wrapped_container().id, port=int(port)
        )
    config.stash[_SHARED] = shared


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: "WorkerController") -> None:
    node.workerinput[_WORKERINPUT_KEY] = {
        name: container.model_dump()
        for name, container in node.config.stash.get(_SHARED, {}).items()
    }


def _shared(config: pytest.Config, name: str) -> SharedContainer:
    shared = (
        config.workerinput[_WORKERINPUT_KEY]
        if hasattr(config, "workerinput")
        else config.stash.get(_SHARED, {})
    )
    if name not in shared:
        pytest.fail(
            f"add {name} to the {_CONTAINERS_INI} ini option", pytrace=False
        )
    return SharedContainer.model_validate(shared[name])


@pytest.fixture(scope="session")
def worker_database(request: pytest.FixtureRequest) -> str:
    config = request.config
    worker = (
        config.workerinput["workerid"]
        if hasattr(config, "workerinput")
        else "master"
    )
    return f"test_{worker}"


@pytest.fixture(scope="session")
def shared_postgres(
    request: pytest.FixtureRequest, worker_database: str
) -> SharedContainer:
    container = _shared(request.config, "postgres")
    with closing(DockerClient().client) as client:
        docker = client.containers.get(container.id)
        # NOTE: a worker xdist restarts after a crash keeps its id, and its
        # database from the first attempt.
        for command in (
            ["dropdb", "-U", "postgres", "--if-exists", worker_database],
            ["createdb", "-U", "postgres", worker_database],
        ):
            exit_code, output = docker.exec_run(command)
            if exit_code != 0:
                pytest.fail(output.decode(), pytrace=False)
    return container


@pytest.fixture(scope="session")
def shared_mongo(request: pytest.FixtureRequest) -> SharedContainer:
    return _shared(request.config, "mongo")
