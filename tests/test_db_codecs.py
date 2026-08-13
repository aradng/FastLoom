from decimal import Decimal

from bson import Decimal128, decode, encode

from fastloom.db.lifehooks import get_mongo_client


async def test_decimal128_decodes_to_decimal():
    client = await get_mongo_client("mongodb://localhost:27017")
    raw = encode({"cost": Decimal128("0.0143125")})

    assert decode(raw, codec_options=client.codec_options) == {
        "cost": Decimal("0.0143125")
    }
