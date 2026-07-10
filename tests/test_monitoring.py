from unittest.mock import Mock

from fastloom.monitoring import (
    Instruments,
    infer_broker_instruments,
    infer_instruments,
    instrument_brokers,
)
from fastloom.observability.settings import ObservabilitySettings
from fastloom.signals.kafka.settings import KafkaSettings
from fastloom.signals.settings import RabbitmqSettings


class _HybridSettings(
    ObservabilitySettings, RabbitmqSettings, KafkaSettings
): ...


def _hybrid_settings(**overrides) -> _HybridSettings:
    return _HybridSettings(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        RABBIT_URI="amqp://guest:guest@localhost:5672/",
        KAFKA_URI="localhost:9092",
        **overrides,
    )


def _observability_settings(**overrides) -> ObservabilitySettings:
    return ObservabilitySettings(
        ENVIRONMENT="test", PROJECT_NAME="fastloom_test", **overrides
    )


def test_infer_broker_instruments_detects_rabbit_and_kafka():
    assert infer_broker_instruments(_hybrid_settings()) == [
        Instruments.RABBIT,
        Instruments.KAFKA,
    ]


def test_infer_broker_instruments_kafka_only():
    settings = KafkaSettings(KAFKA_URI="broker:9092")
    assert infer_broker_instruments(settings) == [Instruments.KAFKA]


def test_infer_broker_instruments_rabbit_only():
    settings = RabbitmqSettings(
        RABBIT_URI="amqp://guest:guest@localhost:5672/"
    )
    assert infer_broker_instruments(settings) == [Instruments.RABBIT]


def test_infer_broker_instruments_empty_without_broker_settings():
    assert infer_broker_instruments(_observability_settings()) == []


def test_infer_instruments_no_longer_includes_broker_instruments():
    # moved to infer_broker_instruments/instrument_brokers — see
    # docs/signals.md#ordering
    instruments = infer_instruments(_hybrid_settings())
    assert Instruments.RABBIT not in instruments
    assert Instruments.KAFKA not in instruments


def test_instrument_brokers_noop_when_otel_disabled(monkeypatch):
    mocked_infer = Mock()
    monkeypatch.setattr(
        "fastloom.monitoring.infer_broker_instruments", mocked_infer
    )

    instrument_brokers(_observability_settings(OTEL_ENABLED=0))

    mocked_infer.assert_not_called()


def test_instrument_brokers_calls_each_inferred_instrument(monkeypatch):
    fake = Mock()
    monkeypatch.setattr(
        "fastloom.monitoring.infer_broker_instruments",
        Mock(return_value=[fake]),
    )

    instrument_brokers(_observability_settings(OTEL_ENABLED=1))

    fake.value.assert_called_once_with()
