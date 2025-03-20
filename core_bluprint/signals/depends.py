import logging
from typing import Annotated, Protocol

from aio_pika import IncomingMessage, Message
from faststream import Context, ExceptionMiddleware
from faststream.broker.message import StreamMessage
from faststream.rabbit import (
    ExchangeType,
    RabbitBroker,
    RabbitExchange,
    RabbitQueue,
)
from faststream.rabbit.fastapi import RabbitRouter
from faststream.rabbit.publisher.asyncapi import AsyncAPIPublisher
from faststream.rabbit.schemas.queue import ClassicQueueArgs
from faststream.rabbit.subscriber.asyncapi import AsyncAPISubscriber
from opentelemetry import trace

from core_bluprint.signals.middlewares import RabbitPayloadTelemetryMiddleware
from core_bluprint.signals.settings import RabbitmqSettings

logger = logging.getLogger(__name__)


def get_rabbit_broker(settings: RabbitmqSettings) -> RabbitBroker:
    broker = RabbitBroker(
        str(settings.RABBITMQ_URI),
        middlewares=(
            RabbitPayloadTelemetryMiddleware(
                tracer_provider=trace.get_tracer_provider()
            ),
        ),
    )
    return broker


def get_rabbit_router(name: str, settings: RabbitmqSettings) -> RabbitRouter:
    return RabbitRouter(
        str(settings.RABBITMQ_URI),
        schema_url=f"/{name}/asyncapi",
        middlewares=(
            RabbitPayloadTelemetryMiddleware(
                tracer_provider=trace.get_tracer_provider()
            ),
        ),
    )


class RabbitSubscriptable(Protocol):
    RABBITMQ_URI: str
    ENVIRONMENT: str
    PROJECT_NAME: str


class RabbitSubscriber:
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
        exceptions: list[type[Exception]] = [Exception],
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
        self._settings = settings
        self.router = get_rabbit_router(
            f"api/{self._settings.PROJECT_NAME}",
            RabbitmqSettings.model_validate(
                {"RABBITMQ_URI": self._settings.RABBITMQ_URI}
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

    def _get_queue(self, name: str) -> RabbitQueue:
        """
        :param name: name of the queue
        :return: RabbitQueue
        """
        return RabbitQueue(
            name=f"{self._queue_prefix}_{name}",
            routing_key=name,
            durable=True,
        )

    async def _get_dlx_queue(
        self,
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
        dlx = await self.router.broker.declare_exchange(self.exchange)

        queue = RabbitQueue(
            name=f"{self._queue_prefix}_{routing_key}."
            f"{self._settings.PROJECT_NAME}.{delay}",
            routing_key=f"{routing_key}.{self._settings.PROJECT_NAME}.{delay}",
            durable=True,
            arguments=ClassicQueueArgs(
                {
                    "x-dead-letter-exchange": self.exchange.name,
                    "x-dead-letter-routing-key": f"{routing_key}."
                    f"{self._settings.PROJECT_NAME}",
                    "x-message-ttl": delay * 1000,
                    "x-expires": delay * 2000,
                }
            ),
        )

        robust_queue = await self.router.broker.declare_queue(
            queue=queue,
        )

        await robust_queue.bind(
            dlx,
            routing_key=f"{routing_key}.{self._settings.PROJECT_NAME}."
            f"{delay}",
        )

        return queue

    async def _exc_handler(
        self,
        exc: Exception,
        message: Annotated[StreamMessage[IncomingMessage], Context()],
    ):
        message.headers["x-delivery-count"] = (
            message.headers.get("x-delivery-count", 0) + 1
        )

        assert isinstance(message.raw_message.routing_key, str)
        if (routing_key := message.raw_message.routing_key).endswith(
            f".{self._settings.PROJECT_NAME}"
        ) and message.headers["x-delivery-count"] > 1:
            routing_key = routing_key[
                : -len(f".{self._settings.PROJECT_NAME}")
            ]
        queue = await self._get_dlx_queue(
            routing_key,
            min(
                self._base_delay
                * 2 ** (message.headers["x-delivery-count"] - 1),
                self._max_delay,
            ),
        )

        await self.router.broker.publish(
            Message(body=message.body, headers=message.headers),
            queue=queue,
            exchange=self.exchange,
            persist=True,
        )
        # re-raise for observability in sentry/otel
        raise exc

    def _get_subscriber(
        self, routing_key: str, **kwargs
    ) -> AsyncAPISubscriber:
        return self.router.subscriber(
            queue=self._get_queue(routing_key),
            exchange=self.exchange,
            **kwargs,
        )

    def subscriber(
        self,
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
            decorators = [self._get_subscriber(routing_key, **kwargs)]
            if retry_backoff:
                decorators.append(
                    self._get_subscriber(
                        f"{routing_key}.{self._settings.PROJECT_NAME}",
                        **kwargs,
                    )
                )
            for decorator in decorators:
                func = decorator(func)

            return func

        return _inner

    def multi_subscriber(
        self,
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
                func = self.subscriber(
                    routing_key,
                    retry_backoff=retry_backoff,
                    **kwargs,
                )(func)
            return func

        return _inner

    def multi_publisher(
        self,
        routing_keys: list[str],
        schema: type | None = None,
        **kwargs,
    ) -> dict[str, AsyncAPIPublisher]:
        """
        :param routing_keys: list of routing keys for the publishers
        :param schema: publish schema for the publishers
        :param kwargs: additional arguments for the faststream publishers
        """
        return {
            routing_key: self.router.publisher(
                exchange=self.exchange,
                routing_key=routing_key,
                schema=schema,
                persist=True,
                **kwargs,
            )
            for routing_key in routing_keys
        }
