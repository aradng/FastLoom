import asyncio

import pytest

from fastloom.meta import SelfSustaining


class Widget(SelfSustaining):
    def __init__(self):
        super().__init__()
        self.name = "widget"


def test_unbound_attr_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="not bound"):
        _ = Widget.name


def test_unbound_self_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="not bound"):
        _ = Widget.self


def test_bound_attr_reads_through() -> None:
    Widget()
    assert Widget.name == "widget"


async def test_bound_in_task_visible_to_sibling_task() -> None:
    # Mirrors uvicorn's LifespanOn: the ASGI lifespan (where production code
    # binds Configs/PGManager/etc.) runs in its own forked task, while
    # request-handling tasks are siblings of the root task, not descendants
    # of the lifespan task. The binding must be visible there too.
    async def bind_it() -> None:
        Widget()

    async def read_it() -> str:
        return Widget.name

    await asyncio.create_task(bind_it())
    assert await asyncio.create_task(read_it()) == "widget"
