import random
import typing
from pprint import pformat

from deepdiff import DeepDiff  # type: ignore[import-untyped]

if typing.TYPE_CHECKING:

    class ResponseType(typing.Protocol):
        status_code: int
        text: str
        is_success: bool


def assert_deep_diff(actual, expected, **options):
    try:
        import bson
        from beanie import PydanticObjectId

        options |= dict(
            ignore_type_in_groups=[(bson.ObjectId, PydanticObjectId, str)]
        )
    except ImportError:
        ...
    diff = DeepDiff(
        expected,
        actual,
        ignore_order=True,
        exclude_types={type(...)},  # ignore comparison with ellipsis
        verbose_level=2,
        ignore_type_subclasses=False,
        ignore_nan_inequality=True,
        **options,
    )
    assert not diff, pformat(diff)


def random_mobile_number():
    return f"0912{random.randint(1000000, 9999999)}"


def status_check(response: "ResponseType", status: int):
    assert response.status_code == status, (
        response.status_code,
        response.text,
    )


def assert_success(response: "ResponseType"):
    assert response.is_success, response.text
