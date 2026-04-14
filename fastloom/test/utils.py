import json
import random
import typing
from itertools import zip_longest
from operator import itemgetter
from unittest.mock import AsyncMock

from deepdiff import DeepDiff
from deepdiff.helper import CannotCompare
from httpx import Response
from jose import jwt
from pydantic import AliasPath, BaseModel

from fastloom.test.constants import SECRET_KEY
from fastloom.test.types import ContainerData

if typing.TYPE_CHECKING:
    # from fastloom.file.schemas import FileMessage

    class ResponseType(typing.Protocol):
        status_code: int
        text: str
        is_success: bool

else:
    ResponseType = Response


def generate_token(
    claims: str,
) -> str:
    return jwt.encode(json.loads(claims), key=SECRET_KEY)


def get_url(container: ContainerData) -> str:
    return ":".join(container[1:])


def assert_deep_diff(
    actual,
    expected,
    key: str | None = None,
    use_compare_func: bool = False,
    **options,
):
    """
    Compares two dictionaries and nested objects and raises AssertionError if
    they are different with a human readable structure error.

    Set `...` to values in either side to ignore comparison for those keys.
    Set `key` when evaluating lists to sort the value and the expected based
    on.
    """
    try:
        import bson
        from beanie import PydanticObjectId

        options |= dict(
            ignore_type_in_groups=[(bson.ObjectId, PydanticObjectId, str)]
        )
    except ImportError:
        ...

    compare_func = None
    group_by = None
    if isinstance(actual, list) and key is not None:
        if use_compare_func:
            compare_func = _iterable_diff_compare_func(key)
            group_by = key
        else:
            _actual_item: dict[str, typing.Any]
            _expected_item: dict[str, typing.Any]
            for _, (_actual_item, _expected_item) in enumerate(
                zip_longest(
                    sorted(actual, key=itemgetter(key)),
                    sorted(expected, key=itemgetter(key)),
                    fillvalue={},
                )
            ):
                assert_deep_diff(_actual_item, _expected_item)
            return None

    diff = DeepDiff(
        expected,
        actual,
        ignore_order=True,
        exclude_types={type(...)},  # ignore comparison with ellipsis
        verbose_level=2,
        ignore_type_subclasses=False,
        ignore_nan_inequality=True,
        iterable_compare_func=compare_func,
        group_by=group_by,
        **options,
    )
    assert not diff, diff.to_json(
        indent=4, default_mapping={type(...): lambda x: "..."}
    )


def _iterable_diff_compare_func(key: str):
    def compare_func(x, y, level=None):
        try:
            return x[key] == y[key]
        except Exception:
            raise CannotCompare() from None

    return compare_func


def random_mobile_number():
    return f"0912{random.randint(1000000, 9999999)}"


def status_check(response: "ResponseType", status: int):
    assert response.status_code == status, (
        response.status_code,
        response.text,
    )


def assert_success(response: "ResponseType"):
    assert response.is_success, response.text


def token_to_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def to_dict(model: BaseModel, **kwargs) -> dict[str, typing.Any]:
    return json.loads(model.model_dump_json(**kwargs))


def ignore_keys(d: dict, *paths: str):
    converted_paths = [
        tuple(
            int(segment) if segment.isdigit() else segment
            for segment in path.split(".")
        )
        for path in paths
    ]
    for key in converted_paths:
        assert isinstance(key[0], str)
        path = AliasPath(key[0], *key[1:-1])
        path.search_dict_for_path(d)[key[-1]] = ...


def expect_calling(
    mock: AsyncMock, expected: list[dict[str, typing.Any]], key: str
):
    """
    Compares the expected and actual calls of a mock object.
    Parameters:
    -----------
    mock : AsyncMock
        The mock object to check
    expected : list[dict[str, typing.Any]]
        The expected calls to the mock object
    key : str
        The key to sort the expected and actual calls by. It helps deepdiff to
        match calls
    """
    mock.assert_called()
    assert_deep_diff(
        [to_dict(call.args[0]) for call in mock.await_args_list],
        expected,
        key=key,
    )


# def expected_file(
#     file_message: "FileMessage", file_message_received_first: bool
# ):
#     """
#     Creates the expected file object based on message order.

#     Parameters:
#     -----------
#     file_message : FileMessage
#         The file message information
#     file_message_received_first : bool
#         Whether the file message was received before the text message

#     Returns:
#     --------
#     MatchedFile or UnmatchedFile
#         The appropriate file object type based on message order
#     """
#     from core_file.schemas import MatchedFile, UnmatchedFile

#     if file_message_received_first:
#         return MatchedFile(
#             name=file_message.name,
#             path=file_message.path,
#             content_type=file_message.content_type,
#             content_length=file_message.content_length,
#         )
#     return UnmatchedFile(
#         name=file_message.name,
#         usage=file_message.usage,
#     )


def assert_no_data(r: Response):
    assert r.status_code == 200, r.text
    assert_deep_diff(r.json(), dict(count=0, data=[]))
