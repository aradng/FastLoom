import random
from pprint import pformat

import bson
from beanie import PydanticObjectId
from deepdiff import DeepDiff
from httpx import Response


def assert_deep_diff(actual, expected, **options):
    diff = DeepDiff(
        expected,
        actual,
        ignore_order=True,
        exclude_types={type(...)},  # ignore comparison with ellipsis
        verbose_level=2,
        ignore_type_in_groups=[(bson.ObjectId, PydanticObjectId, str)],
        ignore_type_subclasses=False,
        ignore_nan_inequality=True,
        **options,
    )
    assert not diff, pformat(diff)


def random_mobile_number():
    return f"0912{random.randint(1000000, 9999999)}"


def status_check(status: int, response: Response):
    assert response.status_code == status, (
        response.status_code,
        response.text,
    )
