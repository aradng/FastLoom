from pydantic import (
    BaseModel,
    Field,
    RedisDsn,
)

from fastloom.types import Str


class RedisSettings(BaseModel):
    REDIS_URL: Str[RedisDsn] = Field(
        "redis://localhost:6379/0", validate_default=True
    )
