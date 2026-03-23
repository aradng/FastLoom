import logging
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from beanie import (
        Delete,
        Document,
        Insert,
        Replace,
        Save,
        SaveChanges,
        Update,
        after_event,
    )
else:
    try:
        from beanie import (
            Delete,
            Document,
            Insert,
            Replace,
            Save,
            SaveChanges,
            Update,
            after_event,
        )
    except ImportError:
        from pydantic import BaseModel as Delete
        from pydantic import BaseModel as Document
        from pydantic import BaseModel as Insert
        from pydantic import BaseModel as Replace
        from pydantic import BaseModel as Save
        from pydantic import BaseModel as SaveChanges
        from pydantic import BaseModel as Update

        def after_event(*args, **kwargs):
            def decorator(func):
                return func

            return decorator


from pydantic import BaseModel, ConfigDict, PrivateAttr, model_validator

from fastloom.signals.depends import RabbitSubscriber

logger = logging.getLogger(__name__)


class Operations(StrEnum):
    CREATE = auto()
    UPDATE = auto()
    DELETE = auto()


class SignalMessage[T: Document](BaseModel):
    instance: T
    changes: dict[str, Any]
    operation: Operations

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")


class BaseDocumentSignal(Document):
    """
    Assumes that this mixin is used with `BaseDocument` subclasses and
    `BaseDocument` has full state management
    """

    _sent_events: set[tuple[UUID, Operations]] = PrivateAttr(
        default_factory=set
    )
    _PROJECT_NAME: str = ""

    @model_validator(mode="after")
    def validate_state_management(self):
        self.get_settings().use_revision = True
        self.get_settings().use_state_management = True
        self.get_settings().state_management_save_previous = True
        self.check_state_management()  # TODO: unsure which to keep
        return self

    async def _publish(self, message: SignalMessage):
        if self.revision_id is None:
            return
        _event_key = (
            self.revision_id,
            message.operation,
        )
        if _event_key in self._sent_events:
            logger.debug(f"prevented publishing event: {_event_key}")
            return
        logger.debug(f"publishing event: {_event_key}")
        await self.get_publisher(message.operation).publish(
            message,
        )
        self._sent_events.add(_event_key)

    @classmethod
    def get_subscription_topic(cls, operation: Operations):
        return (
            f"{cls._PROJECT_NAME}.{cls.get_collection_name()}."
            f"{operation.value}"
        )

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
        return RabbitSubscriber.publisher(
            routing_key=cls.get_subscription_topic(operation),
            schema=SignalMessage[cls],  # type: ignore[valid-type]
        )


class SignalsInsert(BaseDocumentSignal):
    @after_event(Insert)
    async def _publish_post_insert(cls):
        await cls.publish_post_insert()

    async def publish_post_insert(self):
        await self._publish(
            SignalMessage(
                instance=self,
                changes=self.get_previous_changes(),
                operation=Operations.CREATE,
            ),
        )


class SignalsUpdate(BaseDocumentSignal):
    @after_event(Replace, SaveChanges, Update, Save)
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


class SignalsDelete(BaseDocumentSignal):
    @after_event(Delete)
    async def _publish_post_delete(self):
        await self.publish_post_delete()

    async def publish_post_delete(self):
        await self._publish(
            SignalMessage(
                instance=self,
                changes=self.get_previous_changes(),
                operation=Operations.DELETE,
            )
        )


class SignalsAll(SignalsInsert, SignalsUpdate, SignalsDelete): ...
