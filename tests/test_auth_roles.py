from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fastloom.auth.depends import JWTAuth
from fastloom.auth.roles import (
    RoleExpressionError,
    RoleLiteral,
    and_role,
    not_role,
    or_role,
    parse_roles,
)
from fastloom.auth.schemas import UserClaims
from fastloom.auth.settings import IAMSettings


@pytest.mark.parametrize(
    "expression",
    [
        "ADMIN",
        "ADMIN|MEMBER",
        "(ADMIN&SEED)|MEMBER",
        "!TRIAL",
        "CHART:READ&!CHART:TRIAL",
    ],
)
def test_an_expression_renders_back_to_itself(expression):
    assert parse_roles(expression).render() == expression


@pytest.mark.parametrize(
    ("expression", "roles", "granted"),
    [
        ("ADMIN|MEMBER", {"MEMBER"}, True),
        ("ADMIN|MEMBER", {"SEED"}, False),
        ("(ADMIN&SEED)|MEMBER", {"ADMIN"}, False),
        ("(ADMIN&SEED)|MEMBER", {"ADMIN", "SEED"}, True),
        ("!TRIAL", set(), True),
        ("!TRIAL", {"TRIAL"}, False),
        ("ADMIN&!(SEED|TRIAL)", {"ADMIN", "TRIAL"}, False),
    ],
)
def test_an_expression_is_evaluated_against_the_roles(
    expression, roles, granted
):
    assert parse_roles(expression).evaluate(roles) is granted


def _clauses(expression: str) -> list[set[str]]:
    return [
        {("" if lit.present else "!") + lit.name for lit in clause}
        for clause in parse_roles(expression).disjunction()
    ]


@pytest.mark.parametrize(
    ("expression", "clauses"),
    [
        ("(A|B)&C", [{"A", "C"}, {"B", "C"}]),
        ("!(A|B)", [{"!A", "!B"}]),
        ("!(A&B)", [{"!A"}, {"!B"}]),
        ("A&!A", []),
        ("A|A", [{"A"}]),
    ],
)
def test_an_expression_becomes_an_or_of_ands(expression, clauses):
    assert _clauses(expression) == clauses


def test_a_clause_holds_role_literals():
    assert parse_roles("!A").disjunction() == [
        frozenset({RoleLiteral(name="A", present=False)})
    ]


@pytest.mark.parametrize(
    "expression", ["", "A|", "(A", "A B", "A$", "A)", "&A"]
)
def test_a_malformed_expression_is_rejected(expression):
    with pytest.raises(RoleExpressionError):
        parse_roles(expression)


def test_the_helpers_build_the_same_expressions():
    assert (
        or_role(and_role("ADMIN", "SEED"), "MEMBER") == "(ADMIN&SEED)|MEMBER"
    )
    assert not_role(or_role("A", "B")) == "!(A|B)"


def _claims(roles: list[str]) -> UserClaims:
    return UserClaims.model_validate(
        {
            "iss": "http://iam/realms/qubit",
            "sub": "3f1c2a9e-8d4b-4f6a-9c21-7e5b0d8a4c13",
            "sid": "s",
            "preferred_username": "u",
            "name": "U",
            "given_name": "U",
            "family_name": "U",
            "roles": roles,
            "email": "u@example.com",
            "email_verified": True,
            "scope": "openid",
        }
    )


@pytest.mark.parametrize(
    ("roles", "status"), [(["ADMIN", "SEED"], 200), (["ADMIN"], 403)]
)
def test_require_roles_answers_403_when_the_expression_fails(
    monkeypatch, roles, status
):
    auth = JWTAuth(
        IAMSettings(OIDC_URL="http://iam/.well-known/openid-configuration")
    )

    async def validate(token, request):
        return _claims(roles)

    monkeypatch.setattr(auth, "_validate_token", validate)
    app = FastAPI()

    @app.get("/seed")
    def seed(
        claims: Annotated[
            UserClaims, Depends(auth.require_roles("(ADMIN&SEED)|MEMBER"))
        ],
    ) -> list[str]:
        return claims.roles

    response = TestClient(app).get(
        "/seed", headers={"Authorization": "Bearer t"}
    )

    assert response.status_code == status
