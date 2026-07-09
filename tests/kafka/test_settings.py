import pytest
from pydantic import ValidationError

from fastloom.monitoring import Instruments, infer_instruments
from fastloom.signals.kafka.settings import KafkaSettings


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


@pytest.mark.parametrize(
    "raw",
    [
        "broker",
        "broker:not-a-port",
        "broker:9092,",
        "",
        "broker:999999999999",
        "bröker:9092",
        "broker1:9092, broker2:9093",
        "broker1:9092,broker2",
        "broker:0",
        "broker:65536",
    ],
)
def test_kafka_bootstrap_rejects_malformed(raw: str) -> None:
    with pytest.raises(ValidationError):
        KafkaSettings(KAFKA_URI=raw)


def test_kafka_settings_are_auto_instrumented() -> None:
    settings = KafkaSettings(KAFKA_URI="broker:9092")
    assert Instruments.KAFKA in infer_instruments(settings)
