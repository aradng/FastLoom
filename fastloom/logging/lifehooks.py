import logging

from fastloom.logging.settings import LoggingSettings
from fastloom.logging.utils import (
    ColoredFormatter,
    EndpointFilter,
    QueueFilter,
)


def setup_logging(settings: LoggingSettings):
    logger = logging.getLogger()
    handlers = list(
        filter(lambda h: isinstance(h, logging.StreamHandler), logger.handlers)
    )
    if not handlers:
        stream_handler = logging.StreamHandler()
        logger.addHandler(stream_handler)
        handlers.append(stream_handler)
    for handler in handlers:
        handler.setFormatter(ColoredFormatter())

    app_logger = logging.getLogger(settings.PROJECT_NAME)
    app_logger.setLevel(settings.LOG_LEVEL)

    logging.getLogger("uvicorn.access").addFilter(
        EndpointFilter(settings.LOGGING_EXCLUDED_ENDPOINTS)
    )
    logging.getLogger("faststream.access.rabbit").addFilter(
        QueueFilter(settings.LOGGING_EXCLUDED_QUEUES)
    )
