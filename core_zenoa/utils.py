import logging

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
