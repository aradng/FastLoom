import pytest
from pydantic import ValidationError

from fastloom.types import HostPort


@pytest.mark.parametrize(
    ("raw", "host", "port"),
    [
        ("broker:9092", "broker", 9092),
        (("broker", 9092), "broker", 9092),
        (("broker", "9092"), "broker", 9092),
    ],
)
def test_host_port_accepts_string_or_tuple(raw, host: str, port: int) -> None:
    hp = HostPort.model_validate(raw)
    assert hp.root == (host, port)
    assert str(hp) == f"{host}:{port}"


@pytest.mark.parametrize(
    "raw",
    ["broker", "broker:0", "broker:65536", "bröker:9092", ""],
)
def test_host_port_rejects_malformed(raw: str) -> None:
    with pytest.raises(ValidationError):
        HostPort.model_validate(raw)
