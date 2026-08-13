from collections.abc import Callable
from decimal import Decimal
from typing import Any

import orjson
from bson import (
    DBRef,
    Decimal128,
    MaxKey,
    MinKey,
    ObjectId,
    Regex,
)
from bson.binary import (
    ALL_UUID_SUBTYPES,
    VECTOR_SUBTYPE,
    Binary,
    BinaryVector,
)
from bson.raw_bson import RawBSONDocument
from bson.timestamp import Timestamp
from opentelemetry.trace import Span
from pymongo import monitoring


def _parse_binary(obj: Binary):
    if obj.subtype in ALL_UUID_SUBTYPES:
        return obj.as_uuid()
    if obj.subtype == VECTOR_SUBTYPE:
        return repr(obj.as_vector())
    return obj.hex()


_CONVERTERS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
    (RawBSONDocument, dict),
    (Decimal128, lambda o: str(o.to_decimal())),
    (Decimal, str),
    (ObjectId, str),
    (
        DBRef,
        lambda o: {"$ref": o.collection, "$id": str(o.id), "$db": o.database},
    ),
    (Binary, _parse_binary),
    (BinaryVector, repr),
    (bytes, lambda o: o.hex()),
    (Regex, lambda o: {"$regex": o.pattern, "$options": str(o.flags)}),
    (MinKey, lambda o: {"$minKey": 1}),
    (MaxKey, lambda o: {"$maxKey": 1}),
    (
        Timestamp,
        lambda o: {
            "timestamp": o.time,
            "increment": o.inc,
            "datetime": o.as_datetime(),
        },
    ),
)


def _parse_mongo_types(obj):
    for kind, convert in _CONVERTERS:
        if isinstance(obj, kind):
            return convert(obj)
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
