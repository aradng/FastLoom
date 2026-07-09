from pydantic import AmqpDsn, BaseModel

from fastloom.types import Str


class RabbitmqSettings(BaseModel):
    RABBIT_URI: Str[AmqpDsn]
