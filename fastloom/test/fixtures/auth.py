from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl
from pytest_mock import MockerFixture

from fastloom.auth.schemas import ADMIN_ROLE, UserClaims
from fastloom.test.utils import generate_token


@pytest.fixture(autouse=True)
def mock_authz(
    mocker: MockerFixture,
    settings_mock,  # noqa: F811
) -> tuple[MagicMock, ...]:
    return (
        mocker.patch(
            "fastloom.auth.depends.OptionalJWTAuth._acl",
            return_value=None,
        ),
        mocker.patch(
            "fastloom.auth.depends.OptionalJWTAuth._introspect",
            return_value=None,
        ),
    )


@pytest.fixture
def admin_token(admin_claims: UserClaims) -> str:
    return generate_token(admin_claims.model_dump_json())


@pytest.fixture
def user_token(user_claims: UserClaims) -> str:
    return generate_token(user_claims.model_dump_json())


@pytest.fixture
def user_claims(
    tenant_name: str, valid_email: str, user_id: UUID
) -> UserClaims:
    return UserClaims(
        sub=user_id,
        sid=str(uuid4()),
        preferred_username=valid_email,
        name="Test User",
        given_name="test",
        family_name="user",
        email=valid_email,
        email_verified=True,
        iss=HttpUrl(f"https://localhot/{tenant_name}"),
        scope=set(),
    )


@pytest.fixture
def admin_claims(tenant_name: str, admin_user_id: UUID) -> UserClaims:
    return UserClaims(
        sub=admin_user_id,
        sid=str(uuid4()),
        preferred_username="admin@example.com",
        name="Admin User",
        given_name="test",
        family_name="user",
        email="admin@example.com",
        email_verified=True,
        iss=HttpUrl(f"https://localhot/{tenant_name}"),
        scope=set(),
        roles=[ADMIN_ROLE],
    )


@pytest.fixture
def admin_token_headers(admin_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def user_token_headers(user_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def tenant_serial() -> str:
    return str(uuid4().int)[:5]


@pytest.fixture
def tenent_uuid_str() -> str:
    return uuid4().hex


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def admin_user_id() -> UUID:
    return uuid4()


@pytest.fixture
def valid_email(tenant_serial: str):
    return f"email.{tenant_serial}@gmail.com"


@pytest.fixture
def valid_phone(tenant_serial: str):
    return f"+9899912{tenant_serial}"


@pytest.fixture
def tenant_name(tenent_uuid_str: str) -> str:
    return f"test-{tenent_uuid_str}"


@pytest.fixture
def organization_name(tenant_serial: str) -> str:
    return f"test_org_{tenant_serial}"


@pytest.fixture
def organization_id() -> str:
    return str(uuid4())
