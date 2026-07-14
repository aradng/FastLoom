from concurrent.futures import ThreadPoolExecutor

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


def test_unbound_in_other_thread_raises_attribute_error() -> None:
    # NOTE: binding lives in a ContextVar, which threads spawned via a plain
    # ThreadPoolExecutor (e.g. loop.run_in_executor) don't inherit.
    Widget()

    def read_from_thread():
        return Widget.name

    with (
        ThreadPoolExecutor() as executor,
        pytest.raises(AttributeError, match="not bound"),
    ):
        executor.submit(read_from_thread).result()
