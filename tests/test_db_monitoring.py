from decimal import Decimal

import orjson
from bson import Decimal128, MaxKey, MinKey, Regex, encode
from bson.raw_bson import RawBSONDocument

from fastloom.db.monitoring import _parse_mongo_types


def _dumps(reply):
    return orjson.loads(orjson.dumps(reply, default=_parse_mongo_types))


def test_a_raw_write_reply_serializes():
    reply = RawBSONDocument(encode({"n": 1, "updatedExisting": True}))

    assert _dumps(reply) == {"n": 1, "updatedExisting": True}


def test_bson_types_inside_a_raw_reply_still_convert():
    reply = RawBSONDocument(encode({"cost": Decimal128("0.0141")}))

    assert _dumps(reply) == {"cost": "0.0141"}


def test_a_decoded_decimal_serializes():
    assert _dumps({"cost": Decimal("0.0141")}) == {"cost": "0.0141"}


def test_the_remaining_bson_scalars_serialize():
    reply = {"r": Regex("^a", "i"), "lo": MinKey(), "hi": MaxKey()}

    assert _dumps(reply) == {
        "r": {"$regex": "^a", "$options": "re.IGNORECASE"},
        "lo": {"$minKey": 1},
        "hi": {"$maxKey": 1},
    }
