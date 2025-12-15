import re
from typing import Annotated, Any

from pydantic import AfterValidator, Field, GetCoreSchemaHandler, TypeAdapter
from pydantic_core import core_schema

PHONE_REGEX = r"^(\+|00)\d{1,2}\s?((\(\d{3}\))|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}$"
EMAIL_REGEX = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"


class PhoneValidation:
    @classmethod
    def phone_validator(cls, string: str | None) -> str | None:
        if string and re.match(PHONE_REGEX, string):
            string = re.sub(r"^00", "+", string)
            string = re.sub(r"[()\s.-]", "", string)
            return string
        return None

    @classmethod
    def phone_validator_or_exc(cls, string: str) -> str:
        if phone := cls.phone_validator(string):
            return phone
        raise ValueError("Invalid phone number")


class EmailValidation:
    @classmethod
    def email_validator(cls, string: str) -> str | None:
        email_regex = EMAIL_REGEX
        if re.match(email_regex, string):
            return string
        return None


PhoneNumberOrNone = Annotated[
    str | None, AfterValidator(PhoneValidation.phone_validator)
]
ValidatedPhoneNumber = Annotated[
    str, AfterValidator(PhoneValidation.phone_validator_or_exc)
]


def _national_id_validator(nc: str) -> str | None:
    assert "12345678" not in nc
    assert len(nc) == 10
    assert nc.isdigit()
    assert nc not in (str(i) * 10 for i in range(10))
    rem = sum(int(c) * (10 - i) for i, c in enumerate(nc[:9])) % 11
    assert int(nc[9]) == ((11 - rem) if rem >= 2 else rem)
    return nc


NationalID = Annotated[str, AfterValidator(_national_id_validator)]

UserId = str

NoneField = Annotated[None, Field(None)]


class Str[T](str):
    __validator__: Any = None

    @classmethod
    def __class_getitem__(cls, item: Any):
        return type(
            f"Str[{getattr(item, '__name__', repr(item))}]",
            (cls,),
            {"__validator__": item},
        )

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ):
        adapter = TypeAdapter(cls.__validator__)

        def validate(v: str) -> "Str[T]":
            validated = adapter.validate_python(v)
            return cls(str(validated))

        return core_schema.no_info_after_validator_function(
            validate,
            core_schema.str_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema()
            ),
        )
