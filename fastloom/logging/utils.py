import logging
import re
from re import Pattern

import click


class ColoredFormatter(logging.Formatter):
    @staticmethod
    def get_colored_levelname(level_name, levelno):
        level_colors = {
            logging.DEBUG: lambda text: click.style(text, fg="bright_blue"),
            logging.INFO: lambda text: click.style(text, fg="green"),
            logging.WARNING: lambda text: click.style(text, fg="yellow"),
            logging.ERROR: lambda text: click.style(text, fg="red"),
            logging.CRITICAL: lambda text: click.style(text, fg="bright_red"),
        }
        return level_colors.get(levelno, lambda text: text)(level_name)

    def format(self, record):
        formatted_message = super().format(record)
        levelname = self.get_colored_levelname(
            record.levelname, record.levelno
        )
        name = click.style(record.name, fg="magenta")
        message = click.style(formatted_message, fg="bright_cyan")

        colorized_message = f"{levelname}: \t  {name} {message}"
        return colorized_message


class EndpointFilter(logging.Filter):
    def __init__(
        self, excluded_endpoints: tuple[Pattern | str, ...] = ()
    ) -> None:
        super().__init__()
        self.excluded_endpoints = excluded_endpoints

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.args or len(record.args) < 3:
            return True
        endpoint: str = record.args[2]  # type: ignore[assignment, index]
        return not any(
            re.match(exp, endpoint) for exp in self.excluded_endpoints
        )


class QueueFilter(logging.Filter):
    def __init__(self, excluded_queues: tuple[Pattern | str, ...] = ()):
        super().__init__()
        self.excluded_queues = excluded_queues

    def filter(self, record: logging.LogRecord) -> bool:
        queue: str = getattr(record, "queue", "")
        if record.levelno >= logging.ERROR:
            return True
        return not any(re.match(exp, queue) for exp in self.excluded_queues)
