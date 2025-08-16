from gettext import gettext as _

from fastapi import status


class CustomI18NException(Exception):
    message: str
    error_code: int

    def __init__(
        self,
        message: str | None = None,
        err_code: int | None = None,
        *args,
        **kwargs,
    ):
        if message:
            self.message = message
        if err_code:
            self.error_code = err_code

    def __str__(self):
        return f"{self.__class__.__name__}({self.message})"

    @property
    def formatted_message(self):
        return self.message.format(**self.__dict__)


# Global
class SettingNotSet(CustomI18NException):
    message = _("{name} not set")
    error_code = status.HTTP_503_SERVICE_UNAVAILABLE
    name: str

    def __init__(self, name: str):
        self.name = name
        super().__init__(self.message, self.error_code)


class DoesNotExist(CustomI18NException):
    message = _("{name} does not exist")
    error_code = status.HTTP_404_NOT_FOUND
    name: str

    def __init__(self, name: str):
        self.name = name
        super().__init__(self.message, self.error_code)


class OnlyAdminOrOwnerAllowed(CustomI18NException):
    message = _("Only admin or owner allowed to access")
    error_code = status.HTTP_403_FORBIDDEN


class OnlyOwnerAllowed(CustomI18NException):
    message = _("Only owner of {resource} allowed to {action}")
    error_code = status.HTTP_403_FORBIDDEN
    resource: str
    action: str

    def __init__(self, resource: str, action: str):
        self.resource = resource
        self.action = action
        super().__init__(self.message, self.error_code)
