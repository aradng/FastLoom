from pydantic import AmqpDsn, BaseModel


class RabbitmqSettings(BaseModel):
    RABBITMQ_URI: AmqpDsn
