from pydantic import (
    BaseModel,
    Field,
    RedisDsn,
)


class RedisSettings(BaseModel):
    redis_url: RedisDsn = Field(RedisDsn("redis://localhost:6379/0"))
