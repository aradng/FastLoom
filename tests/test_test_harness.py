import json
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from docker.errors import NotFound
from pydantic import BaseModel
from testcontainers.core.docker_client import DockerClient

from fastloom.test.container import PrivateRegistryDocker
from fastloom.test.fixtures import shared
from fastloom.test.fixtures.settings import patched_settings

pytest_plugins = ["pytester"]

_PLUGIN = ("-p", "fastloom.test.fixtures.shared")


def _login(monkeypatch: pytest.MonkeyPatch, registry: str | None) -> MagicMock:
    if registry is None:
        monkeypatch.delenv("REGISTRY_ADDRESS", raising=False)
    else:
        monkeypatch.setenv("REGISTRY_ADDRESS", registry)
    monkeypatch.setenv("REGISTRY_USERNAME", "user")
    monkeypatch.setenv("REGISTRY_PASSWORD", "secret")
    container = PrivateRegistryDocker("redis")
    container._docker = MagicMock()
    container._configure()
    return container._docker.login


@pytest.mark.parametrize("registry", [None, ""])
def test_no_registry_skips_the_login(
    monkeypatch: pytest.MonkeyPatch, registry: str | None
):
    _login(monkeypatch, registry).assert_not_called()


def test_a_registry_logs_in(monkeypatch: pytest.MonkeyPatch):
    auth = _login(monkeypatch, "registry.example").call_args.kwargs[
        "auth_config"
    ]
    assert (auth.registry, auth.username, auth.password) == (
        "registry.example",
        "user",
        "secret",
    )


class _Settings(BaseModel):
    pass


def test_settings_are_dumped_only_when_loaded(mocker):
    dump = mocker.patch(
        "fastloom.tenant.utils.dump_settings", return_value="default: {}"
    )
    load = mocker.patch("fastloom.tenant.utils.load_settings")
    with patched_settings(_Settings()):
        settings = import_module("fastloom.tenant.settings")
        dump.assert_not_called()
        settings.load_settings()
        settings.load_settings()
    dump.assert_called_once()
    assert load.call_count == 2
    assert load.call_args.kwargs["config_stream"] == "default: {}"


def test_workers_get_the_controllers_containers():
    container = shared.SharedContainer(id="abc", port=5432)
    config = SimpleNamespace(stash={shared._SHARED: {"postgres": container}})
    node = SimpleNamespace(config=config, workerinput={})

    shared.pytest_configure_node(node)

    worker = SimpleNamespace(workerinput=node.workerinput)
    assert shared._shared(worker, "postgres") == container


_INI = "[pytest]\nfastloom_shared_containers =\n    postgres\n    mongo\n"


def test_listing_the_tests_starts_no_container(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
):
    started = MagicMock()
    monkeypatch.setitem(shared._STARTERS, "postgres", started)
    monkeypatch.setitem(shared._STARTERS, "mongo", started)
    pytester.makeini(_INI)
    pytester.makepyfile("def test_nothing(shared_postgres):\n    pass\n")

    for flag in ("--collect-only", "--fixtures", "--setup-plan"):
        assert pytester.runpytest_inprocess(*_PLUGIN, flag).ret == 0

    started.assert_not_called()


def test_a_fixture_for_an_unlisted_container_fails(pytester: pytest.Pytester):
    pytester.makepyfile("def test_nothing(shared_postgres):\n    pass\n")

    result = pytester.runpytest_inprocess(*_PLUGIN)

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*add postgres to the fastloom_shared_containers ini option*"]
    )


def test_an_unknown_shared_container_is_a_usage_error(
    pytester: pytest.Pytester,
):
    pytester.makeini("[pytest]\nfastloom_shared_containers = oracle\n")
    pytester.makepyfile("def test_nothing():\n    pass\n")

    result = pytester.runpytest_inprocess(*_PLUGIN)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert (
        "fastloom_shared_containers: unknown ['oracle'], "
        "expected any of ['mongo', 'postgres']"
    ) in result.stderr.str()


_RECORD = """
import json
import os

from testcontainers.core.docker_client import DockerClient


def test_record(shared_postgres, shared_mongo, worker_database):
    exit_code, output = (
        DockerClient()
        .client.containers.get(shared_postgres.id)
        .exec_run(
            ["psql", "-U", "postgres", "-tAc",
             "SELECT datname FROM pg_database"]
        )
    )
    assert exit_code == 0, output
    with open(os.path.join(os.environ["OUT"], worker_database), "w") as f:
        json.dump(
            {
                "postgres": shared_postgres.id,
                "mongo": shared_mongo.id,
                "databases": output.decode().split(),
            },
            f,
        )
"""


@pytest.mark.parametrize(
    "args, workers",
    [
        (("-n", "2", "--dist", "each"), {"test_gw0", "test_gw1"}),
        (("-p", "no:xdist"), {"test_master"}),
    ],
    ids=["two-workers", "no-xdist"],
)
def test_one_postgres_and_mongo_with_a_database_per_worker(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    args: tuple[str, ...],
    workers: set[str],
):
    out = pytester.mkdir("out")
    monkeypatch.setenv("OUT", str(out))
    pytester.makeini(_INI)
    pytester.makepyfile(_RECORD)

    result = pytester.runpytest_subprocess(*_PLUGIN, *args, timeout=300)

    result.assert_outcomes(passed=len(workers))
    recorded = {
        path.name: json.loads(path.read_text()) for path in out.iterdir()
    }
    assert set(recorded) == workers
    assert all(
        workers <= set(record["databases"]) for record in recorded.values()
    )
    ids = {
        (record["postgres"], record["mongo"]) for record in recorded.values()
    }
    ((postgres_id, mongo_id),) = ids
    client = DockerClient().client
    for container_id in (postgres_id, mongo_id):
        with pytest.raises(NotFound):
            client.containers.get(container_id)
