import json
from importlib import import_module
from unittest.mock import MagicMock

import pytest
from docker.errors import NotFound
from pydantic import BaseModel
from testcontainers.core.docker_client import DockerClient

from fastloom.test.container import PrivateRegistryDocker
from fastloom.test.fixtures.settings import patched_settings

pytest_plugins = ["pytester"]


def _configured(monkeypatch, registry: str | None) -> MagicMock:
    if registry is None:
        monkeypatch.delenv("REGISTRY_ADDRESS", raising=False)
    else:
        monkeypatch.setenv("REGISTRY_ADDRESS", registry)
    container = PrivateRegistryDocker("redis")
    container._docker = MagicMock()
    container._configure()
    return container._docker.login


def test_no_registry_skips_the_login(monkeypatch):
    _configured(monkeypatch, None).assert_not_called()


def test_a_registry_logs_in(monkeypatch):
    login = _configured(monkeypatch, "registry.example")
    assert login.call_args.kwargs["auth_config"].registry == "registry.example"


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
    assert load.call_args.kwargs["config_stream"] == "default: {}"


_SHARED_TESTS = """
import json
import os

import pytest


@pytest.mark.parametrize("n", range(4))
def test_records(shared_postgres, worker_database, n):
    with open(os.path.join(os.environ["OUT"], worker_database), "w") as f:
        json.dump(shared_postgres.model_dump(), f)
"""


def test_workers_share_one_postgres_with_a_database_each(
    pytester, monkeypatch
):
    out = pytester.mkdir("out")
    monkeypatch.setenv("OUT", str(out))
    pytester.makeini(
        "[pytest]\nfastloom_shared_containers = postgres\n"
        "fastloom_postgres_image = postgres:18\n"
    )
    pytester.makepyfile(_SHARED_TESTS)

    result = pytester.runpytest_subprocess(
        "-n", "2", "-p", "fastloom.test.fixtures.shared"
    )

    result.assert_outcomes(passed=4)
    recorded = {
        path.name: json.loads(path.read_text()) for path in out.iterdir()
    }
    assert set(recorded) == {"test_gw0", "test_gw1"}
    (container_id,) = {container["id"] for container in recorded.values()}
    with pytest.raises(NotFound):
        DockerClient().client.containers.get(container_id)


def test_an_unknown_shared_container_is_a_usage_error(pytester):
    pytester.makeini("[pytest]\nfastloom_shared_containers = oracle\n")
    pytester.makepyfile("def test_nothing():\n    pass\n")

    result = pytester.runpytest_subprocess(
        "-p", "fastloom.test.fixtures.shared"
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*unknown*oracle*"])
