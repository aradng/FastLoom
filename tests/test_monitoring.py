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


class _HybridSettings(ObservabilitySettings, RabbitmqSettings, KafkaSettings):
    pass


def _hybrid_settings(**overrides) -> _HybridSettings:
    return _HybridSettings(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        RABBIT_URI="amqp://guest:guest@localhost:5672/",
        KAFKA_URI="localhost:9092",
        **overrides,
    )


def test_infer_broker_instruments_detects_rabbit_and_kafka():
    assert infer_broker_instruments(_hybrid_settings()) == [
        Instruments.RABBIT,
        Instruments.KAFKA,
    ]


def test_infer_broker_instruments_empty_without_broker_settings():
    settings = ObservabilitySettings(
        ENVIRONMENT="test", PROJECT_NAME="fastloom_test"
    )
    assert infer_broker_instruments(settings) == []


def test_infer_instruments_no_longer_includes_broker_instruments():
    # Broker instrumentation moved to infer_broker_instruments/
    # instrument_brokers so it can run before either subscriber
    # constructs — see docs/signals.md#ordering. infer_instruments must
    # not re-include them, or InitMonitoring would double-instrument.
    instruments = infer_instruments(_hybrid_settings())
    assert Instruments.RABBIT not in instruments
    assert Instruments.KAFKA not in instruments


def test_instrument_brokers_noop_when_otel_disabled(monkeypatch):
    fake = Mock()
    monkeypatch.setattr(
        "fastloom.monitoring.infer_broker_instruments",
        Mock(return_value=[fake]),
    )

    instrument_brokers(_hybrid_settings(OTEL_ENABLED=0))

    fake.value.assert_not_called()


def test_instrument_brokers_calls_each_inferred_instrument(monkeypatch):
    fake = Mock()
    monkeypatch.setattr(
        "fastloom.monitoring.infer_broker_instruments",
        Mock(return_value=[fake]),
    )

    instrument_brokers(_hybrid_settings(OTEL_ENABLED=1))

    fake.value.assert_called_once_with()
