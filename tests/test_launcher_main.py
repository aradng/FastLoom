from unittest.mock import MagicMock, Mock

from fastapi import APIRouter

import fastloom.launcher.main as launcher_main
from fastloom.observability.settings import ObservabilitySettings
from fastloom.settings.base import FastAPISettings
from fastloom.signals.kafka.settings import KafkaSettings
from fastloom.signals.settings import RabbitmqSettings


class _LauncherTestSettings(
    ObservabilitySettings, RabbitmqSettings, KafkaSettings, FastAPISettings
): ...


def test_app_runs_early_monitoring_and_constructs_subscribers_before_get_app(
    monkeypatch,
):
    settings = _LauncherTestSettings(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        RABBIT_URI="amqp://guest:guest@localhost:5672/",
        KAFKA_URI="localhost:9092",
        SENTRY_ENABLED=1,
    )
    configs = MagicMock()
    configs.__getitem__.return_value.general = settings

    manager = Mock()
    service_app = Mock(additional_instruments=[], otel_sampling=None)

    mocks = {
        "Configs": configs,
        "get_settings_cls": Mock(),
        "get_tenant_cls": Mock(),
        "get_app": Mock(return_value=service_app),
        "init_early_monitoring": Mock(),
        "RabbitSubscriber": Mock(router=APIRouter()),
        "KafkaSubscriber": Mock(router=APIRouter()),
        "InitMonitoring": MagicMock(),
    }
    for name, mock in mocks.items():
        manager.attach_mock(mock, name)
        monkeypatch.setattr(launcher_main, name, mock)

    launcher_main.app.__wrapped__()

    call_order = [call[0] for call in manager.mock_calls]
    positions = [
        call_order.index(name)
        for name in (
            "init_early_monitoring",
            "RabbitSubscriber",
            "KafkaSubscriber",
            "get_app",
            "InitMonitoring",
        )
    ]
    assert positions == sorted(positions)
