from typing import Self, cast


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
