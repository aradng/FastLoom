import random
from pprint import pformat

import bson
from beanie import PydanticObjectId
from deepdiff import DeepDiff


def assert_deep_diff(actual, expected, **options):
    # ignore comparison with ellipsis
    diff = DeepDiff(
        expected,
        actual,
        ignore_order=True,
        exclude_types={type(...)},
        verbose_level=2,
        ignore_type_in_groups=[(bson.ObjectId, PydanticObjectId, str)],
        ignore_type_subclasses=False,
        ignore_nan_inequality=True,
        **options,
    )
    assert not diff, pformat(diff)


def random_mobile_number():
    return f"0912{random.randint(1000000, 9999999)}"
    # return "09190624272"
