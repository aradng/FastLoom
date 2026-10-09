import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from itertools import product

from pydantic import BaseModel, ConfigDict

ROLE_TOKEN = re.compile(r"\s*(?:([A-Za-z0-9_.:\-]+)|([|&!()]))")


class RoleLiteral(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    present: bool


type Clause = frozenset[RoleLiteral]


class RoleExpression(BaseModel, ABC):
    model_config = ConfigDict(frozen=True)

    @abstractmethod
    def evaluate(self, roles: Iterable[str]) -> bool: ...

    @abstractmethod
    def clauses(self, negated: bool = False) -> list[Clause]: ...

    @abstractmethod
    def render(self) -> str: ...

    def disjunction(self) -> list[Clause]:
        unique = {
            clause
            for clause in self.clauses()
            if not any(
                RoleLiteral(name=lit.name, present=not lit.present) in clause
                for lit in clause
            )
        }
        return sorted(
            unique,
            key=lambda c: sorted((lit.name, not lit.present) for lit in c),
        )


class Role(RoleExpression):
    name: str

    def evaluate(self, roles: Iterable[str]) -> bool:
        return self.name in roles

    def clauses(self, negated: bool = False) -> list[Clause]:
        return [frozenset({RoleLiteral(name=self.name, present=not negated)})]

    def render(self) -> str:
        return self.name


class Not(RoleExpression):
    operand: "RoleExpression"

    def evaluate(self, roles: Iterable[str]) -> bool:
        return not self.operand.evaluate(roles)

    def clauses(self, negated: bool = False) -> list[Clause]:
        return self.operand.clauses(not negated)

    def render(self) -> str:
        inner = self.operand.render()
        return f"!{inner}" if isinstance(self.operand, Role) else f"!({inner})"


class And(RoleExpression):
    operands: tuple["RoleExpression", ...]

    def evaluate(self, roles: Iterable[str]) -> bool:
        return all(op.evaluate(roles) for op in self.operands)

    def clauses(self, negated: bool = False) -> list[Clause]:
        if negated:
            return [c for op in self.operands for c in op.clauses(True)]
        return [
            frozenset().union(*combo)
            for combo in product(*(op.clauses() for op in self.operands))
        ]

    def render(self) -> str:
        return "&".join(
            f"({op.render()})" if isinstance(op, Or) else op.render()
            for op in self.operands
        )


class Or(RoleExpression):
    operands: tuple["RoleExpression", ...]

    def evaluate(self, roles: Iterable[str]) -> bool:
        return any(op.evaluate(roles) for op in self.operands)

    def clauses(self, negated: bool = False) -> list[Clause]:
        if negated:
            return [
                frozenset().union(*combo)
                for combo in product(
                    *(op.clauses(True) for op in self.operands)
                )
            ]
        return [c for op in self.operands for c in op.clauses()]

    def render(self) -> str:
        return "|".join(
            f"({op.render()})" if isinstance(op, And) else op.render()
            for op in self.operands
        )


class RoleExpressionError(ValueError): ...


class _Parser:
    def __init__(self, expression: str):
        self.expression = expression
        self.tokens = self._tokenize(expression)
        self.position = 0

    def _tokenize(self, expression: str) -> list[str]:
        tokens = []
        position = 0
        while position < len(expression.rstrip()):
            match = ROLE_TOKEN.match(expression, position)
            if match is None:
                raise RoleExpressionError(
                    f"unexpected {expression[position:]!r} in {expression!r}"
                )
            tokens.append(match.group(1) or match.group(2))
            position = match.end()
        return tokens

    def _peek(self) -> str | None:
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise RoleExpressionError(
                f"{self.expression!r} ends where a role was expected"
            )
        self.position += 1
        return token

    def parse(self) -> RoleExpression:
        expression = self._or()
        if self._peek() is not None:
            raise RoleExpressionError(
                f"unexpected {self._peek()!r} in {self.expression!r}"
            )
        return expression

    def _or(self) -> RoleExpression:
        operands = [self._and()]
        while self._peek() == "|":
            self._take()
            operands.append(self._and())
        return operands[0] if len(operands) == 1 else Or(operands=operands)

    def _and(self) -> RoleExpression:
        operands = [self._not()]
        while self._peek() == "&":
            self._take()
            operands.append(self._not())
        return operands[0] if len(operands) == 1 else And(operands=operands)

    def _not(self) -> RoleExpression:
        token = self._take()
        if token == "!":
            return Not(operand=self._not())
        if token == "(":
            expression = self._or()
            if self._take() != ")":
                raise RoleExpressionError(
                    f"unbalanced parentheses in {self.expression!r}"
                )
            return expression
        if token in {"|", "&", ")"}:
            raise RoleExpressionError(
                f"unexpected {token!r} in {self.expression!r}"
            )
        return Role(name=token)


def parse_roles(expression: str) -> RoleExpression:
    return _Parser(expression).parse()


def and_role(*expressions: str) -> str:
    return And(operands=tuple(map(parse_roles, expressions))).render()


def or_role(*expressions: str) -> str:
    return Or(operands=tuple(map(parse_roles, expressions))).render()


def not_role(expression: str) -> str:
    return Not(operand=parse_roles(expression)).render()
