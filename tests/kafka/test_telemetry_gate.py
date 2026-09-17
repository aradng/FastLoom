from fastloom.observability.settings import ObservabilitySettings
from fastloom.signals.kafka.depends import get_kafka_router
from fastloom.signals.kafka.settings import KafkaSettings


class _Observable(ObservabilitySettings, KafkaSettings): ...


def _middleware_names(router) -> list[str]:
    return [
        getattr(m, "__name__", type(m).__name__)
        for m in router.broker.middlewares
    ]


def _router(settings):
    return get_kafka_router(
        settings,
        allow_auto_create_topics=True,
        acks=1,
        enable_idempotence=False,
    )


def test_telemetry_middleware_is_added_when_otel_is_on():
    settings = _Observable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI="broker:9092",
        OTEL_ENABLED=1,
    )
    names = _middleware_names(_router(settings))
    assert "KafkaTelemetryMiddleware" in names


def test_telemetry_middleware_is_absent_when_otel_is_off():
    settings = _Observable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI="broker:9092",
        OTEL_ENABLED=0,
    )
    assert "KafkaTelemetryMiddleware" not in _middleware_names(
        _router(settings)
    )


def test_settings_without_the_flag_do_not_get_telemetry():
    settings = KafkaSettings(KAFKA_URI="broker:9092")
    assert "KafkaTelemetryMiddleware" not in _middleware_names(
        _router(settings)
    )
