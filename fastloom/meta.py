import inspect
from pathlib import Path
from typing import Any, Self, cast

import tomllib
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo


class SelfSustainingMeta(type):
    def __new__(mcls, name, bases, namespace):
        namespace["self"] = cast(object, None)  # reserve the slot
        return super().__new__(mcls, name, bases, namespace)

    def __getattr__(cls, name):
        if cls.self is None:
            raise AttributeError(f"{cls.__name__}.self is not initialized")

        return getattr(cls.self, name)

    def __setattr__(cls, name, value):
        if name == "self" or name in cls.__dict__:
            return super().__setattr__(name, value)
        if name == "__parameters__":
            return super().__setattr__(name, value)
        if cls.self is None:
            raise AttributeError(f"{cls.__name__}.self is not initialized")
        return setattr(cls.self, name, value)


class SelfSustaining(metaclass=SelfSustainingMeta):
    self: Self

    def __init__(self, *args, **kwargs):
        type(self).self = self  # store the singleton


def optional_fieldinfo(
    field: FieldInfo, strip: bool = False
) -> tuple[Any, FieldInfo]:
    field = field._copy()
    if field.is_required() or strip:
        field.default = None
        field.default_factory = None
        field.validate_default = False
        if field.annotation is not None:
            field.annotation = cast(type[Any], field.annotation | None)
    return field.annotation, field


def create_optional_model[T: BaseModel](
    model: type[T], strip: bool = False, name: str | None = None
) -> type[T]:
    return create_model(
        f"Optional{model.__name__}" if name is None else name,
        **{
            k: cast(Any, optional_fieldinfo(v, strip=strip))
            for k, v in model.model_fields.items()
        },
    )


def infer_project_name():
    file = (
        Path(
            next(
                filter(
                    lambda x: (
                        __name__.split(".")[0] not in x.filename
                        and ".venv" not in x.filename
                        and "site-packages" not in x.filename
                    ),
                    inspect.stack(),
                ),
            ).filename
        ).parent
        / "pyproject.toml"
    )
    if not file.exists():
        raise FileNotFoundError(
            "Could not find pyproject.toml to infer project name"
        )
    data = tomllib.loads(file.read_text())
    project_name = (
        data.get("project", {}).get("name")  # PEP 621
        or data.get("tool", {}).get("poetry", {}).get("name")  # Poetry
    )
    if not isinstance(project_name, str):
        raise ValueError("Could not infer project name in pyproject.toml")
    return project_name
