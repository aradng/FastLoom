import pytest
from pydantic import ValidationError

from fastloom.signals.settings import KafkaSettings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("broker:9092", "broker:9092"),
        ("kafka://broker:9092", "broker:9092"),
        ("broker1:9092,broker2:9093", "broker1:9092,broker2:9093"),
        (
            "kafka://broker1:9092,broker2:9093",
            "broker1:9092,broker2:9093",
        ),
    ],
)
def test_kafka_bootstrap_accepts(raw: str, expected: str) -> None:
    assert expected == KafkaSettings(KAFKA_URI=raw).KAFKA_URI


def test_kafka_bootstrap_round_trips() -> None:
    once = KafkaSettings(KAFKA_URI="kafka://broker:9092").KAFKA_URI
    twice = KafkaSettings(KAFKA_URI=once).KAFKA_URI
    assert once == twice == "broker:9092"


@pytest.mark.parametrize(
    "raw",
    [
        "broker",
        "broker:not-a-port",
        "broker:9092,",
        "",
    ],
)
def test_kafka_bootstrap_rejects_malformed(raw: str) -> None:
    with pytest.raises(ValidationError):
        KafkaSettings(KAFKA_URI=raw)
