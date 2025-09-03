from pydantic import AmqpDsn, BaseModel


class RabbitmqSettings(BaseModel):
    RABBIT_URI: AmqpDsn
