import logging
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID

from beanie import Insert, Replace, SaveChanges, Update, after_event
from pydantic import BaseModel, PrivateAttr, model_validator

from core_zenoa.db.schemas import BaseDocument
from core_zenoa.signals.depends import get_stream_router

logger = logging.getLogger(__name__)

stream_router = get_stream_router(__name__)


class Operations(str, Enum):
    UPDATE = "update"
    SAVE = "save"


T = TypeVar("T", bound=BaseDocument)


class SignalMessage(BaseModel, Generic[T]):
    instance: T
    changes: dict[str, Any]
    operation: Operations


class BaseDocumentSignal(BaseModel):
    """
    Assumes that this mixin is used with `BaseDocument` subclasses and
    `BaseDocument` has full state management
    """

    _sent_events: set[tuple[UUID, Operations]] = PrivateAttr(
        default_factory=set
    )

    @model_validator(mode="after")
    def validate_state_management(self):
        self.check_state_management()
        return self

    async def _publish(self, message: SignalMessage):
        _event_key = (
            self.revision_id,  # type: ignore[attr-defined]
            message.operation,
        )
        if _event_key in self._sent_events:
            logger.debug(f"prevented publishing event: {_event_key}")
            return
        logger.debug(f"publishing event: {_event_key}")
        await self.get_publisher(message.operation).publish(message)
        self._sent_events.add(_event_key)

    @classmethod
    def get_subscription_topic(cls, operation: Operations):
        return f"{cls.Settings.name}.{operation.value}"  # type: ignore[attr-defined]  # noqa

    @classmethod
    def check_state_management(cls):
        if not (
            cls.use_state_management() and cls.state_management_save_previous()
        ):
            raise ValueError(
                f"State management is not enabled for {cls.__name__}"
            )

    @classmethod
    def get_publisher(cls, operation: Operations):
        return stream_router.broker.publisher(
            cls.get_subscription_topic(operation)
        )


class SignalsSave(BaseDocumentSignal):
    @after_event(Insert)
    async def _publish_post_save(self):
        await self.publish_post_save()

    async def publish_post_save(self):
        await self._publish(
            SignalMessage(
                instance=self,
                changes=self.get_previous_changes(),
                operation=Operations.SAVE,
            ),
        )


class SignalsUpdate(BaseDocumentSignal):
    @after_event(Replace, SaveChanges, Update)
    async def _publish_post_update(self):
        await self.publish_post_update()

    async def publish_post_update(self):
        await self._publish(
            SignalMessage(
                instance=self,
                changes=self.get_previous_changes(),
                operation=Operations.UPDATE,
            )
        )
        # TODO: We can maybe send separate signals for each field change?
