import logging
from typing import Any

from aio_pika import Message
from faststream import ExceptionMiddleware
from faststream.rabbit import (
    ExchangeType,
    RabbitExchange,
    RabbitMessage,
    RabbitQueue,
)
from faststream.rabbit.fastapi import RabbitRouter
from faststream.rabbit.publisher.usecase import RabbitPublisher
from faststream.rabbit.schemas.queue import ClassicQueueArgs
from opentelemetry import trace

from fastloom.meta import SelfSustaining
from fastloom.settings.base import MonitoringSettings
from fastloom.signals.middlewares import RabbitPayloadTelemetryMiddleware
from fastloom.signals.settings import RabbitmqSettings

logger = logging.getLogger(__name__)


def get_rabbit_router(name: str, settings: RabbitmqSettings) -> RabbitRouter:
    return RabbitRouter(
        settings.RABBIT_URI,
        schema_url=f"/{name}/asyncapi",
        middlewares=(
            RabbitPayloadTelemetryMiddleware(
                tracer_provider=trace.get_tracer_provider()
            ),
        ),
    )


class RabbitSubscriptable(RabbitmqSettings, MonitoringSettings): ...


class RabbitSubscriber(SelfSustaining):
    """A class to encapsulate the common logic for RabbitMQ subscribers"""

    router: RabbitRouter
    exchange: RabbitExchange
    exc_middleware: ExceptionMiddleware
    _settings: RabbitSubscriptable
    _base_delay: int
    _max_delay: int
    _queue_prefix: str

    def __init__(
        self,
        settings: RabbitSubscriptable,
        base_delay: int = 5,
        max_delay: int = 3600 * 24,
        exceptions: list[type[Exception]] | None = None,
    ):
        """
        :param settings: settings object with
        RABBIT_URI, ENVIRONMENT, PROJECT_NAME
        :param base_delay: base delay for retrying messages
        :param max_delay: max delay for retrying messages
        :param exceptions: list of exceptions to retry

        creates a RabbitMQ router, exchange, and exception middleware \n
        example usage:
            ```
            rabbit_subscriber = RabbitSubscriber(settings)
            app.include_router(rabbit_subscriber.router)

            @rabbit_subscriber.subscriber("routing_key", with_backoff=True)
            async def handler(message: StreamMessage[IncomingMessage]): ...
            ```
        """
        super().__init__()
        self._settings = settings
        if exceptions is None:
            exceptions = [Exception]
        self.router = get_rabbit_router(
            f"api/{self._settings.PROJECT_NAME}",
            RabbitmqSettings.model_validate(
                self._settings, from_attributes=True
            ),
        )
        self.exchange = RabbitExchange(
            name="amq.topic", type=ExchangeType.TOPIC, durable=True
        )
        self.exc_middleware = ExceptionMiddleware(
            handlers={exc: self._exc_handler for exc in exceptions}
        )
        self.router.broker.add_middleware(self.exc_middleware)
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._queue_prefix = (
            f"{self._settings.ENVIRONMENT}_{self._settings.PROJECT_NAME}"
        )

    @classmethod
    def _get_queue_name(cls, name: str) -> str:
        return f"{cls._queue_prefix}.{name}"

    @classmethod
    def _dlx_suffix(
        cls,
    ) -> str:
        return f".{cls._settings.PROJECT_NAME}"

    @classmethod
    def _get_dlx_name(
        cls,
        routing_key: str,
    ) -> str:
        return f"{cls._get_queue_name(routing_key)}{cls._dlx_suffix()}"

    @classmethod
    def _sanitize_routing_key(cls, routing_key: str) -> str:
        return routing_key.replace("*", "__all__")

    @classmethod
    def _get_queue(cls, name: str) -> RabbitQueue:
        """
        :param name: name of the queue
        :return: RabbitQueue
        """
        return RabbitQueue(
            name=cls._get_queue_name(cls._sanitize_routing_key(name)),
            routing_key=name,
            durable=True,
        )

    @classmethod
    async def _get_dlx_queue(
        cls,
        routing_key: str,
        delay: int,
    ) -> RabbitQueue:
        """
        :param routing_key: routing key for the queue
        :param delay: delay in seconds
        :return: RabbitQueue

        creates a dead letter queue with specified delay
        and binds it to the exchange
        """

        queue = RabbitQueue(
            name=f"{cls._get_dlx_name(cls._sanitize_routing_key(routing_key))}.{delay}",
            routing_key=f"{routing_key}{cls._dlx_suffix()}.{delay}",
            durable=True,
            arguments=ClassicQueueArgs(
                {
                    "x-dead-letter-exchange": cls.exchange.name,
                    "x-dead-letter-routing-key": (
                        f"{routing_key}{cls._dlx_suffix()}"
                    ),
                    "x-message-ttl": delay * 1000,
                    # "x-expires": delay * 2000,
                }
            ),
        )

        robust_queue = await cls.router.broker.declare_queue(
            queue=queue,
        )
        dlx = await cls.router.broker.declare_exchange(cls.exchange)
        await robust_queue.bind(
            dlx,
            routing_key=f"{routing_key}{cls._dlx_suffix()}.{delay}",
        )

        return queue

    @classmethod
    async def _exc_handler(
        cls,
        exc: Exception,
        message: RabbitMessage,
    ):
        message.headers["x-delivery-count"] = (
            message.headers.get("x-delivery-count", 0) + 1
        )
        if message.raw_message.routing_key is None:
            raise exc
        if (routing_key := message.raw_message.routing_key).endswith(
            cls._dlx_suffix()
        ) and message.headers["x-delivery-count"] > 1:
            routing_key = routing_key[: -len(cls._dlx_suffix())]

        queue = await cls._get_dlx_queue(
            routing_key,
            min(
                cls._base_delay
                * 2 ** (message.headers["x-delivery-count"] - 1),
                cls._max_delay,
            ),
        )

        await cls.router.broker.publish(
            Message(body=message.body, headers=message.headers),
            queue=queue,
            exchange=cls.exchange,
            persist=True,
        )
        # re-raise for observability in sentry/otel
        raise exc

    @classmethod
    def _get_subscriber(cls, routing_key: str, **kwargs):
        return cls.router.subscriber(
            queue=cls._get_queue(routing_key),
            exchange=cls.exchange,
            **kwargs,
        )

    @classmethod
    def subscriber(
        cls,
        routing_key: str,
        retry_backoff: bool = False,
        **kwargs,
    ):
        """
        :param routing_key: routing key for the queue
        :param retry_backoff: whether to retry with backoff
        :param kwargs: additional faststream subscriber arguments
        :return: custom decorator for the subscriber
        """

        def _inner(func):
            decorators = [cls._get_subscriber(routing_key, **kwargs)]
            if retry_backoff:
                decorators.append(
                    cls._get_subscriber(
                        f"{routing_key}{cls._dlx_suffix()}",
                        **kwargs,
                    )
                )
            for decorator in decorators:
                func = decorator(func)

            return func

        return _inner

    @classmethod
    def publisher(
        cls,
        routing_key: str,
        schema: Any | None = None,
        **kwargs,
    ):
        """
        :param routing_key: routing key
        :param schema : pydantic schema
        :param kwargs: additional faststream subscriber arguments
        :return: persistent publisher
        """
        return cls.router.publisher(
            routing_key=routing_key,
            exchange=cls.exchange,
            schema=schema,
            persist=True,
            **kwargs,
        )

    @classmethod
    def multi_subscriber(
        cls,
        routing_keys: list[str],
        retry_backoff: bool = False,
        **kwargs,
    ):
        """
        :param routing_keys: list of routing keys for the subscribers
        :param retry_backoff: whether to retry with backoff
        :param kwargs: additional faststream subscriber arguments
        """

        def _inner(func):
            for routing_key in routing_keys:
                func = cls.subscriber(
                    routing_key,
                    retry_backoff=retry_backoff,
                    **kwargs,
                )(func)
            return func

        return _inner

    @classmethod
    def multi_publisher(
        cls,
        routing_keys: dict[str, str],
        schema: type | None = None,
        **kwargs,
    ) -> dict[str, RabbitPublisher]:
        """
        :param routing_keys: list of routing keys for the publishers
        :param schema: publish schema for the publishers
        :param kwargs: additional arguments for the faststream publishers
        """
        return {
            key: cls.router.publisher(
                exchange=cls.exchange,
                routing_key=routing_key,
                schema=schema,
                persist=True,
                **kwargs,
            )
            for key, routing_key in routing_keys.items()
        }
