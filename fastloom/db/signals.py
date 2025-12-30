import logging
import os
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from beanie import Document, Insert, Replace, SaveChanges, Update, after_event
from pydantic import BaseModel, PrivateAttr, create_model, model_validator

from fastloom.signals.depends import RabbitSubscriber

logger = logging.getLogger(__name__)


class Operations(str, Enum):
    UPDATE = "update"
    SAVE = "save"


class SignalMessage[T: Document](BaseModel):
    instance: T
    changes: dict[str, Any]
    operation: Operations


class BaseDocumentSignal(Document):
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
        if self.revision_id is None:
            return
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
        project_name = os.getenv("PROJECT_NAME")
        if not project_name:
            raise ValueError("PROJECT_NAME environment variable is not set")
        return f"{project_name}.{cls.get_collection_name()}.{operation.value}"  # type: ignore[attr-defined]  # noqa

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
        class_changes = create_model(  # type: ignore[call-overload]
            f"{cls.__name__}Changes",
            __base__=cls,
            field_definitions={
                field_name: (f"{field_info.annotation | None}", None)
                for field_name, field_info in cls.model_fields.items()
            },
        )
        class_instance = create_model(  # type: ignore[call-overload]
            f"{cls.__name__}Instance",
            __base__=cls,
            field_definitions={
                field_name: (field_info.annotation, ...)
                for field_name, field_info in cls.model_fields.items()
            },
        )
        # NOTE: ^ to avoid discriminator error because AsyncAPI has issues with
        # it. Otherwise we would've defined __base__ of
        # `narrowed_signal_message` to `SignalMessage[cls]` and wouldn't have
        # overridden `instance`.
        narrowed_signal_message = create_model(
            f"{cls.__name__}SignalMessage",
            __base__=SignalMessage,
            instance=(class_instance, ...),
            changes=(class_changes, ...),
            operation=(Literal[operation], ...),
        )
        return RabbitSubscriber.publisher(
            routing_key=cls.get_subscription_topic(operation),
            schema=narrowed_signal_message,
        )


class SignalsSave(BaseDocumentSignal):
    @after_event(Insert)
    async def _publish_post_save(cls):
        await cls.publish_post_save()

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
