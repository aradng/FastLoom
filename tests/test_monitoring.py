from unittest.mock import Mock

import pytest

from fastloom.monitoring import (
    Instruments,
    drop_mcp_client_errors,
    infer_broker_instruments,
    infer_instruments,
    instrument_brokers,
)
from fastloom.observability.settings import ObservabilitySettings
from fastloom.signals.kafka.settings import KafkaSettings
from fastloom.signals.rabbit.settings import RabbitmqSettings


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


def test_infer_broker_instruments_detects_rabbit_only_of_the_two():
    assert infer_broker_instruments(_hybrid_settings()) == [Instruments.RABBIT]


def test_kafka_is_traced_by_faststream_not_the_otel_instrumentor():
    settings = KafkaSettings(KAFKA_URI="broker:9092")
    assert infer_broker_instruments(settings) == []


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
    assert not hasattr(Instruments, "KAFKA")


def test_instrument_brokers_noop_when_otel_disabled(monkeypatch):
    mocked_infer = Mock()
    monkeypatch.setattr(
        "fastloom.monitoring.infer_broker_instruments", mocked_infer
    )

    instrument_brokers(_observability_settings(OTEL_ENABLED=0))

    mocked_infer.assert_not_called()


def _mcp_event(status: int | None, *, logger: str = "fastmcp.server.server"):
    import httpx

    if status is None:
        exc: BaseException = RuntimeError("fastmcp fell over")
    else:
        request = httpx.Request("GET", "http://localhost/thing")
        response = httpx.Response(status, request=request)
        try:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ValueError(f"HTTP error {status}") from e
        except ValueError as e:
            exc = e
    return (
        {"logger": logger},
        {"exc_info": (type(exc), exc, exc.__traceback__)},
    )


@pytest.mark.parametrize("status", [400, 403, 404, 409, 422, 499])
def test_drop_mcp_client_errors_discards_client_errors(status):
    event, hint = _mcp_event(status)

    assert drop_mcp_client_errors(event, hint) is None


@pytest.mark.parametrize("status", [500, 502, 503])
def test_drop_mcp_client_errors_keeps_server_errors(status):
    event, hint = _mcp_event(status)

    assert drop_mcp_client_errors(event, hint) is event


def test_drop_mcp_client_errors_keeps_non_http_failures():
    event, hint = _mcp_event(None)

    assert drop_mcp_client_errors(event, hint) is event


def test_drop_mcp_client_errors_ignores_other_loggers():
    event, hint = _mcp_event(404, logger="assistant.repo.chart")

    assert drop_mcp_client_errors(event, hint) is event


def test_drop_mcp_client_errors_keeps_events_without_exceptions():
    event = {"logger": "fastmcp.server.server"}

    assert drop_mcp_client_errors(event, {}) is event


def test_drop_mcp_client_errors_ignores_a_merely_contextual_client_error():
    import httpx

    request = httpx.Request("GET", "http://localhost/thing")
    response = httpx.Response(404, request=request)
    try:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            # deliberately unchained: __cause__ stays None, __context__ is set
            raise RuntimeError("a real bug while handling it")  # noqa: B904
    except RuntimeError as e:
        exc = e

    assert exc.__cause__ is None
    assert isinstance(exc.__context__, httpx.HTTPStatusError)

    event = {"logger": "fastmcp.server.server"}
    hint = {"exc_info": (type(exc), exc, exc.__traceback__)}

    assert drop_mcp_client_errors(event, hint) is event


def test_drop_mcp_client_errors_survives_a_cyclic_cause_chain():
    a, b = ValueError("a"), TypeError("b")
    try:
        try:
            raise a from b
        except ValueError:
            raise b from a
    except TypeError:
        pass

    assert a.__cause__ is b and b.__cause__ is a

    event = {"logger": "fastmcp.server.server"}
    hint = {"exc_info": (type(a), a, a.__traceback__)}

    assert drop_mcp_client_errors(event, hint) is event
