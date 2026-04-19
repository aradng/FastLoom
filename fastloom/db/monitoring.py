import orjson
from bson import (
    DBRef,
    Decimal128,
    ObjectId,
)
from bson.binary import (
    ALL_UUID_SUBTYPES,
    VECTOR_SUBTYPE,
    Binary,
    BinaryVector,
)
from bson.timestamp import Timestamp
from opentelemetry.trace import Span
from pymongo import monitoring


def _parse_mongo_types(obj):
    if isinstance(obj, Decimal128):
        return str(obj.to_decimal())
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, DBRef):
        return {
            "$ref": obj.collection,
            "$id": str(obj.id),
            "$db": obj.database,
        }
    if isinstance(obj, Binary) and obj.subtype in ALL_UUID_SUBTYPES:
        return obj.as_uuid()
    if isinstance(obj, Binary) and obj.subtype == VECTOR_SUBTYPE:
        return repr(obj.as_vector())
    if isinstance(obj, BinaryVector):
        return repr(obj)
    if isinstance(obj, Binary | bytes):
        return obj.hex()
    if isinstance(obj, Timestamp):
        return {
            "timestamp": obj.time,
            "increment": obj.inc,
            "datetime": obj.as_datetime(),
        }
    raise TypeError(obj)


def response_hook(span: Span, event: monitoring.CommandSucceededEvent):
    if span and span.is_recording():
        span.set_attribute(
            "db.mongodb.server_reply",
            orjson.dumps(
                event.reply,
                default=_parse_mongo_types,
                option=orjson.OPT_NAIVE_UTC,
            ).decode(),
        )
