import orjson
from bson import Decimal128, encode
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
