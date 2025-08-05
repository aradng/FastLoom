import telnetlib

from faststream.rabbit.fastapi import RabbitRouter


class RabbitConnectionError(Exception): ...


async def check_rabbit_connection(router: RabbitRouter) -> None:
    RABBIT_DEFAULT_PORT: int = 5672
    try:
        assert router.broker._connection, (
            "RabbitMQ connection is not established"
        )
        host: str | None = router.broker._connection.url.host
        port: int = router.broker._connection.url.port or RABBIT_DEFAULT_PORT
        with telnetlib.Telnet(host, port, timeout=1):
            return None
    except Exception as er:
        raise RabbitConnectionError(f"RabbitMQ connection error: {er}") from er
