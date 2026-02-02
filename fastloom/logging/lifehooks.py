import logging

import click

from fastloom.logging.settings import LoggingSettings
from fastloom.settings.base import ProjectSettings
from fastloom.tenant.settings import ConfigAlias as Configs


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


def setup_logging():
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

    app_logger = logging.getLogger(
        Configs[ProjectSettings].general.PROJECT_NAME
    )
    app_logger.setLevel(Configs[LoggingSettings].general.LOG_LEVEL)
