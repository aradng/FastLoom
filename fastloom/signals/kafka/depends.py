from __future__ import annotations

import asyncio
import logging
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Union,
    get_args,
    get_origin,
)

from fastloom.meta import SelfSustaining
from fastloom.signals.kafka.settings import KafkaSettings, KafkaSubscriptable
from fastloom.signals.utils import exponential_backoff

if TYPE_CHECKING:
    from collections.abc import Sequence

    from faststream._internal.types import BrokerMiddleware
    from faststream.confluent.fastapi import KafkaRouter
    from faststream.confluent.message import KafkaMessage
    from faststream.confluent.parser import AsyncConfluentParser
    from faststream.confluent.publisher.producer import (
        AsyncConfluentFastProducerImpl,
    )
    from faststream.confluent.response import KafkaPublishCommand
    from faststream.middlewares import AckPolicy

logger = logging.getLogger(__name__)


class Tombstone:
    """Sentinel marking a message body as a genuine null value - not a byte
    pattern (`b"null"`, `b""`), so it can never collide with real content."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "TOMBSTONE"

    def __bool__(self) -> bool:
        return False

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any):
        from pydantic_core import core_schema

        return core_schema.is_instance_schema(cls)

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: Any, handler: Any):
        return {"const": "TOMBSTONE"}


TOMBSTONE = Tombstone()


def get_kafka_router(
    settings: KafkaSettings,
    middlewares: Sequence[BrokerMiddleware[Any, Any]] = (),
    allow_auto_create_topics: bool = True,
    acks: Literal[0, 1, -1, "all"] = 1,
    enable_idempotence: bool = False,
) -> KafkaRouter:
    # deferred: see docs/signals.md#ordering
    from faststream.confluent.fastapi import KafkaRouter
    from faststream.confluent.parser import AsyncConfluentParser
    from faststream.confluent.publisher.producer import (
        AsyncConfluentFastProducerImpl,
    )

    _patch_real_tombstones(AsyncConfluentFastProducerImpl)
    _patch_tombstone_consumption(AsyncConfluentParser)

    return KafkaRouter(
        settings.KAFKA_URI,
        schema_url="/kafkaapi",
        acks=acks,
        enable_idempotence=enable_idempotence,
        allow_auto_create_topics=allow_auto_create_topics,
        middlewares=middlewares,
    )


def _patch_real_tombstones(
    producer_cls: type[AsyncConfluentFastProducerImpl],
) -> None:
    # NOTE: publish(None, ...) isn't a real Kafka tombstone - the codec
    # turns None into b"", and compaction only reclaims a key on a literal
    # null value (ag2ai/faststream#1967). The real fix (ag2ai/faststream#2932)
    # is merged upstream but PyPI rejects packages with direct git/URL
    # dependencies, so we can't just point at git main - keep this shim until
    # faststream cuts an actual PyPI release containing it. Wraps .publish()
    # in place, at the same deferred point get_kafka_router() imports from -
    # see docs/signals.md#ordering.
    if getattr(producer_cls, "_fastloom_real_tombstones", False):
        return

    original_publish = producer_cls.publish

    async def publish(
        self: AsyncConfluentFastProducerImpl, cmd: KafkaPublishCommand
    ):
        if cmd.body is not None:
            return await original_publish(self, cmd)

        headers_to_send = {"content-type": "", **cmd.headers_to_publish()}
        return await self._producer.producer.send(  # noqa: SLF001
            topic=cmd.destination,
            value=None,
            key=cmd.key,
            partition=cmd.partition,
            timestamp_ms=cmd.timestamp_ms,
            headers=[
                (i, (j or "").encode()) for i, j in headers_to_send.items()
            ],
            no_confirm=cmd.no_confirm,
        )

    producer_cls.publish = publish
    producer_cls._fastloom_real_tombstones = True


def _patch_tombstone_consumption(
    parser_cls: type[AsyncConfluentParser],
) -> None:
    # NOTE: consumer-side half of the same gap - a real tombstone decodes to
    # b"" (parse_message()'s own `or b""`), so a typed Optional[Model] body
    # param still crash-loops: FastAPI's body-solving flattens the model's
    # own required fields rather than ever seeing "no body at all"
    # (ag2ai/faststream#2933, open, no PyPI release either way). Tags the
    # body with a dedicated sentinel at parse time; by default decode_message
    # collapses it to None, matching #2933's own Optional[Model] = None
    # behavior exactly. A handler typed Model | Tombstone opts out of that
    # collapse instead - see _patch_fastapi_body_wrapping.
    if getattr(parser_cls, "_fastloom_tombstone_consumption", False):
        return

    original_parse_message = parser_cls.parse_message
    original_decode_message = parser_cls.decode_message

    async def parse_message(self: AsyncConfluentParser, message: Any):
        parsed = await original_parse_message(self, message)
        if message.value() is None:
            parsed.body = TOMBSTONE
        return parsed

    async def decode_message(self: AsyncConfluentParser, msg: Any):
        if msg.body is TOMBSTONE:
            return None
        return await original_decode_message(self, msg)

    parser_cls.parse_message = parse_message
    parser_cls.decode_message = decode_message
    parser_cls._fastloom_tombstone_consumption = True

    _patch_fastapi_body_wrapping()


def _accepts_tombstone(annotation: Any) -> bool:
    """Whether a handler's declared body type opts into the raw sentinel."""
    if annotation is Tombstone:
        return True

    if get_origin(annotation) in (Union, UnionType):
        return any(_accepts_tombstone(arg) for arg in get_args(annotation))

    return False


_fastapi_route_patched = False


def _patch_fastapi_body_wrapping() -> None:
    global _fastapi_route_patched
    if _fastapi_route_patched:
        return
    _fastapi_route_patched = True

    import inspect
    from itertools import dropwhile

    import faststream._internal.fastapi.route as route

    def build_faststream_to_fastapi_parser(
        *,
        dependent: Any,
        fastapi_config: Any,
        context: Any,
        response_field: Any,
        response_model_include: Any,
        response_model_exclude: Any,
        response_model_by_alias: Any,
        response_model_exclude_unset: Any,
        response_model_exclude_defaults: Any,
        response_model_exclude_none: Any,
    ) -> Any:
        assert dependent.call

        consume = route.make_fastapi_execution(
            dependent=dependent,
            fastapi_config=fastapi_config,
            response_field=response_field,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
        )

        dependencies_names = tuple(i.name for i in dependent.dependencies)
        call_params = inspect.signature(dependent.call).parameters
        first_arg = next(
            dropwhile(lambda i: i in dependencies_names, call_params),
            None,
        )
        first_arg_accepts_tombstone = (
            first_arg is not None
            and _accepts_tombstone(call_params[first_arg].annotation)
        )

        async def parsed_consumer(message: Any) -> Any:
            if first_arg_accepts_tombstone and message.body is TOMBSTONE:
                body: Any = TOMBSTONE
            else:
                body = await message.decode()

            fastapi_body: dict[str, Any] | list[Any] | None | Tombstone
            if first_arg is not None:
                if isinstance(body, dict):
                    path = fastapi_body = body or {}
                elif (
                    isinstance(body, list) or body is None or body is TOMBSTONE
                ):
                    fastapi_body, path = body, {}
                else:
                    path = fastapi_body = {first_arg: body}

                stream_message = route.StreamMessage(
                    body=fastapi_body,
                    headers={"context__": context, **message.headers},
                    path={**path, **message.path},
                )
            else:
                stream_message = route.StreamMessage(
                    body={},
                    headers={"context__": context},
                    path={},
                )

            return await consume(stream_message, message)

        return parsed_consumer

    route.build_faststream_to_fastapi_parser = (
        build_faststream_to_fastapi_parser
    )


class KafkaSubscriber(SelfSustaining):
    """Owns the shared FastStream KafkaRouter singleton."""

    router: KafkaRouter
    _base_delay: int
    _max_delay: int
    _exceptions: tuple[type[Exception], ...]
    _retry_state: dict[tuple[str, int], tuple[int, int]]

    def __init__(
        self,
        settings: KafkaSubscriptable,
        base_delay: int = 5,
        max_delay: int = 1800,
        exceptions: list[type[Exception]] | None = None,
        ack_policy: AckPolicy | None = None,
        allow_auto_create_topics: bool = True,
        acks: Literal[0, 1, -1, "all"] = 1,
        enable_idempotence: bool = False,
    ):
        """
        :param settings: settings object with KAFKA_URI
        :param base_delay: base delay (seconds) before the first retry
        :param max_delay: delay cap (seconds) for repeated retries. This
            sleep blocks the whole subscriber's poll loop (all its
            partitions/topics), not just the failing one - register with
            FastStream's `max_workers>1` if other partitions need to keep
            flowing during a backoff.
        :param exceptions: exception types that trigger backoff (default:
            all exceptions)
        :param ack_policy: broker-wide default ack policy (default:
            NACK_ON_ERROR, required for backoff to actually redeliver).
            Individual `@subscriber(...)` calls can still override it.
        :param allow_auto_create_topics: create a topic on subscribe if it
            doesn't exist yet, instead of erroring. Pass `TC.general.DEBUG`
            from the launcher to disable this outside of local dev.
        :param acks: producer durability - `1` (leader-only ack) is the
            default; use `"all"` for topics where losing a message on
            leader failover is unacceptable.
        :param enable_idempotence: dedupe producer-retried writes at the
            broker. Forces `acks="all"` internally; off by default since
            most producers don't need exactly-once-per-session writes.
        """
        from faststream import BaseMiddleware
        from faststream.middlewares import AckPolicy as _AckPolicy

        super().__init__()
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._exceptions = tuple(exceptions or [Exception])
        self._retry_state = {}
        subscriber = self

        class _RetryMiddleware(BaseMiddleware):
            async def consume_scope(self, call_next, msg):
                key_offset = subscriber._partition_key(msg)
                try:
                    result = await call_next(msg)
                except subscriber._exceptions:
                    if key_offset is not None and msg.is_manual:
                        await subscriber._backoff(*key_offset)
                    raise
                else:
                    if key_offset is not None:
                        subscriber._clear_retry_state(*key_offset)
                    return result

        self.router = get_kafka_router(
            settings,
            middlewares=[_RetryMiddleware],
            allow_auto_create_topics=allow_auto_create_topics,
            acks=acks,
            enable_idempotence=enable_idempotence,
        )
        # broker.config.ack_policy is a read-only composition of every
        # subscriber's own config - this is the one underlying dataclass
        # it actually reads from, so setting it here becomes the default
        # for any subscriber that doesn't pass its own ack_policy=.
        self.router.broker.config.broker_config.ack_policy = (
            ack_policy if ack_policy is not None else _AckPolicy.NACK_ON_ERROR
        )

    @staticmethod
    def _partition_key(
        message: KafkaMessage,
    ) -> tuple[tuple[str, int], int] | None:
        raw = message.raw_message
        first = raw[0] if isinstance(raw, tuple) else raw
        topic, partition, offset = (
            first.topic(),
            first.partition(),
            first.offset(),
        )
        if topic is None or partition is None or offset is None:
            return None
        return (topic, partition), offset

    def _clear_retry_state(self, key: tuple[str, int], offset: int) -> None:
        last = self._retry_state.get(key)
        if last is not None and last[0] == offset:
            self._retry_state.pop(key, None)

    async def _backoff(self, key: tuple[str, int], offset: int) -> None:
        last_offset, last_attempt = self._retry_state.get(key, (None, 0))
        attempt = last_attempt + 1 if last_offset == offset else 1
        self._retry_state[key] = (offset, attempt)

        delay = exponential_backoff(attempt, self._base_delay, self._max_delay)
        logger.warning(
            "kafka consumer error, retrying %s[%s]@%s in %.2fs (attempt %s)",
            key[0],
            key[1],
            offset,
            delay,
            attempt,
        )
        await asyncio.sleep(delay)
