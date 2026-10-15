import pytest

from fastloom.auth.schemas import UserClaims

CLAIMS = {
    "iss": "https://auth.example.com/realms/default",
    "sub": "3965aa71-e809-410d-9939-900b1ef7efdd",
    "preferred_username": "bob",
    "name": "Bob Key",
    "given_name": "Bob",
    "family_name": "Key",
    "email": "bob@example.com",
    "email_verified": True,
    "scope": "profile email curve:read",
}


@pytest.mark.parametrize(("extra", "sid"), [({}, None), ({"sid": "s1"}, "s1")])
def test_user_claims_sid_is_optional(
    extra: dict[str, str], sid: str | None
) -> None:
    assert UserClaims.model_validate({**CLAIMS, **extra}).sid == sid
