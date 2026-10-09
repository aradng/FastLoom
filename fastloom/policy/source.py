import ast
import importlib
from collections.abc import Callable, Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from fastloom.auth.roles import (
    And,
    RoleExpression,
    and_role,
    not_role,
    or_role,
    parse_roles,
)
from fastloom.meta import read_project_name

ROUTE_DECORATORS = {
    "get": "GET",
    "put": "PUT",
    "post": "POST",
    "delete": "DELETE",
    "patch": "PATCH",
    "head": "HEAD",
    "options": "OPTIONS",
    "websocket": "GET",
}
UNREADABLE_ROUTER_CALLS = {
    "include_router",
    "add_api_route",
    "add_api_websocket_route",
    "add_route",
    "route",
}
ROLE_HELPERS: dict[str, Callable[..., str]] = {
    "and_role": and_role,
    "or_role": or_role,
    "not_role": not_role,
}
AUTH_DEPENDENCIES = {"get_claims", "get_token"}
DEPENDENCY_MARKERS = {"Depends", "Security"}


class PolicySourceError(Exception): ...


class Route(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str
    path: str
    authenticated: bool
    roles: RoleExpression | None

    @property
    def access(self) -> str:
        if self.roles is not None:
            return self.roles.render()
        return "user" if self.authenticated else "open"


class Guard(BaseModel):
    model_config = ConfigDict(frozen=True)

    authenticated: bool = False
    roles: tuple[str, ...] = ()

    def __or__(self, other: "Guard") -> "Guard":
        return Guard(
            authenticated=self.authenticated or other.authenticated,
            roles=self.roles + other.roles,
        )

    def expression(self) -> RoleExpression | None:
        if not self.roles:
            return None
        if len(self.roles) == 1:
            return parse_roles(self.roles[0])
        return And(operands=tuple(map(parse_roles, self.roles)))


class Reference(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    module: str
    name: str
    node: ast.AST | None = None


class ModuleReference(Reference): ...


class FunctionReference(Reference): ...


class ClassReference(Reference): ...


class ValueReference(Reference): ...


class ExternalReference(Reference): ...


def dotted(node: ast.expr) -> list[str]:
    match node:
        case ast.Name(id=name):
            return [name]
        case ast.Attribute(value=value, attr=attr):
            return [*dotted(value), attr]
        case ast.Call(func=func):
            return dotted(func)
    return []


def last_name(node: ast.expr) -> str | None:
    names = dotted(node)
    return names[-1] if names else None


class ServiceSource:
    def __init__(self, root: Path):
        self.root = root
        self.modules: dict[str, tuple[ast.Module, bool] | None] = {}

    def module(self, name: str) -> tuple[ast.Module, bool] | None:
        if name not in self.modules:
            base = self.root.joinpath(*name.split("."))
            for path, is_package in (
                (base.with_suffix(".py"), False),
                (base / "__init__.py", True),
            ):
                if path.exists():
                    self.modules[name] = (
                        ast.parse(path.read_text(), filename=str(path)),
                        is_package,
                    )
                    break
            else:
                self.modules[name] = None
        return self.modules[name]

    def tree(self, name: str) -> ast.Module:
        loaded = self.module(name)
        if loaded is None:
            raise PolicySourceError(f"cannot find module {name} in the repo")
        return loaded[0]

    def absolute(self, module: str, target: str | None, level: int) -> str:
        if level == 0:
            assert target is not None
            return target
        loaded = self.module(module)
        assert loaded is not None
        parts = module.split(".")
        package = parts if loaded[1] else parts[:-1]
        base = package[: len(package) - (level - 1)]
        return ".".join([*base, *([target] if target else [])])

    def import_target(self, name: str) -> Reference:
        if self.module(name) is not None:
            return ModuleReference(module=name, name=name)
        return ExternalReference(module=name, name=name)

    def defined(
        self, module: str, stmt: ast.stmt, name: str
    ) -> Reference | None:
        match stmt:
            case ast.FunctionDef() | ast.AsyncFunctionDef() if (
                stmt.name == name
            ):
                return FunctionReference(module=module, name=name, node=stmt)
            case ast.ClassDef() if stmt.name == name:
                return ClassReference(module=module, name=name, node=stmt)
            case ast.Assign(targets=targets, value=value) if any(
                isinstance(t, ast.Name) and t.id == name for t in targets
            ):
                return ValueReference(module=module, name=name, node=value)
            case ast.AnnAssign(
                target=ast.Name(id=target), value=ast.expr() as value
            ) if target == name:
                return ValueReference(module=module, name=name, node=value)
        return None

    def imported(
        self, module: str, stmt: ast.stmt, name: str
    ) -> Reference | None:
        found: Reference | None = None
        match stmt:
            case ast.ImportFrom(module=target, names=aliases, level=level):
                for alias in aliases:
                    if (alias.asname or alias.name) == name:
                        found = self.from_import(
                            self.absolute(module, target, level), alias.name
                        )
            case ast.Import(names=aliases):
                for alias in aliases:
                    if alias.asname == name:
                        found = self.import_target(alias.name)
                    elif (
                        alias.asname is None
                        and alias.name.split(".")[0] == name
                    ):
                        found = self.import_target(name)
        return found

    def lookup(
        self, module: str, statements: list[ast.stmt], name: str
    ) -> Reference | None:
        found: Reference | None = None
        for stmt in statements:
            candidate = self.defined(module, stmt, name)
            if candidate is None:
                candidate = self.imported(module, stmt, name)
            if candidate is not None:
                found = candidate
        return found

    def resolve_name(self, module: str, name: str) -> Reference:
        found = self.lookup(module, self.tree(module).body, name)
        if found is None:
            return ExternalReference(module="builtins", name=name)
        return found

    def from_import(self, base: str, name: str) -> Reference:
        if self.module(f"{base}.{name}") is not None:
            return ModuleReference(module=f"{base}.{name}", name=name)
        if self.module(base) is not None:
            return self.resolve_name(base, name)
        return ExternalReference(module=base, name=name)

    def resolve(self, module: str, node: ast.expr) -> Reference | None:
        match node:
            case ast.Name(id=name):
                return self.resolve_name(module, name)
            case ast.Attribute(value=value, attr=attr):
                base = self.resolve(module, value)
                match base:
                    case ModuleReference():
                        return self.resolve_name(base.module, attr)
                    case ExternalReference():
                        return ExternalReference(
                            module=f"{base.module}.{base.name}"
                            if base.module != base.name
                            else base.module,
                            name=attr,
                        )
                    case ClassReference(node=ast.ClassDef(body=body)):
                        return self.lookup(base.module, body, attr)
        return None

    def string(self, module: str, node: ast.expr) -> str:
        match node:
            case ast.Constant(value=str() as text):
                return text
            case ast.JoinedStr():
                raise PolicySourceError(
                    f"{module}:{node.lineno}: an f-string cannot be read "
                    "without running the code; build role expressions with "
                    "and_role, or_role and not_role instead"
                )
            case ast.Call(func=func, args=args) if (
                last_name(func) in ROLE_HELPERS
            ):
                helper = ROLE_HELPERS[last_name(func) or ""]
                return helper(*(self.string(module, arg) for arg in args))
        reference = self.resolve(module, node)
        match reference:
            case ValueReference(module=owner, node=ast.expr() as value):
                return self.string(owner, value)
            case ExternalReference(module=owner, name=name):
                try:
                    value = getattr(importlib.import_module(owner), name)
                except (ImportError, AttributeError) as e:
                    raise PolicySourceError(
                        f"{module}:{getattr(node, 'lineno', '?')}: cannot "
                        f"read {owner}.{name}"
                    ) from e
                if isinstance(value, str):
                    return str(value)
        raise PolicySourceError(
            f"{module}:{getattr(node, 'lineno', '?')}: cannot read "
            f"{ast.unparse(node)} as a string without running the code"
        )

    def dependency_guard(
        self, module: str, node: ast.expr, seen: frozenset[str]
    ) -> Guard:
        if isinstance(node, ast.Call):
            if last_name(node.func) == "require_roles":
                if not node.args:
                    raise PolicySourceError(
                        f"{module}:{node.lineno}: require_roles needs its "
                        "role expression as the first argument"
                    )
                expression = self.string(module, node.args[0])
                parse_roles(expression)
                return Guard(authenticated=True, roles=(expression,))
            if isinstance(self.resolve(module, node.func), FunctionReference):
                raise PolicySourceError(
                    f"{module}:{node.lineno}: cannot read the dependency "
                    f"returned by {ast.unparse(node)}"
                )
            return Guard()
        names = dotted(node)
        if names and names[-1] in AUTH_DEPENDENCIES:
            return Guard(authenticated="optional_auth" not in names)
        reference = self.resolve(module, node)
        if isinstance(reference, FunctionReference):
            key = f"{reference.module}.{reference.name}"
            if key in seen:
                return Guard()
            assert isinstance(
                reference.node, ast.FunctionDef | ast.AsyncFunctionDef
            )
            return self.parameters_guard(
                reference.module, reference.node.args, seen | {key}
            )
        return Guard()

    def marker_guard(
        self, module: str, node: ast.expr | None, seen: frozenset[str]
    ) -> Guard:
        if not (
            isinstance(node, ast.Call)
            and last_name(node.func) in DEPENDENCY_MARKERS
        ):
            return Guard()
        dependency = next(
            iter(node.args),
            next(
                (k.value for k in node.keywords if k.arg == "dependency"),
                None,
            ),
        )
        if dependency is None:
            return Guard()
        return self.dependency_guard(module, dependency, seen)

    def parameters_guard(
        self, module: str, arguments: ast.arguments, seen: frozenset[str]
    ) -> Guard:
        candidates: list[ast.expr | None] = [
            *arguments.defaults,
            *arguments.kw_defaults,
        ]
        for arg in [
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ]:
            match arg.annotation:
                case ast.Subscript(
                    value=value, slice=ast.Tuple(elts=[_, *metadata])
                ) if last_name(value) == "Annotated":
                    candidates.extend(metadata)
        guard = Guard()
        for candidate in candidates:
            guard |= self.marker_guard(module, candidate, seen)
        return guard

    def dependencies_guard(self, module: str, call: ast.Call) -> Guard:
        guard = Guard()
        for keyword in call.keywords:
            if keyword.arg == "dependencies":
                if not isinstance(keyword.value, ast.List | ast.Tuple):
                    raise PolicySourceError(
                        f"{module}:{call.lineno}: dependencies must be a "
                        "literal list to be read without running the code"
                    )
                for item in keyword.value.elts:
                    guard |= self.marker_guard(module, item, frozenset())
        return guard

    def keyword_string(self, module: str, call: ast.Call, name: str) -> str:
        return next(
            (
                self.string(module, k.value)
                for k in call.keywords
                if k.arg == name
            ),
            "",
        )

    def router_routes(
        self, reference: ValueReference, prefix: str
    ) -> Iterable[Route]:
        if not (
            isinstance(reference.node, ast.Call)
            and last_name(reference.node.func) == "APIRouter"
        ):
            raise PolicySourceError(
                f"{reference.module}.{reference.name} is not an APIRouter(...)"
            )
        module, variable, router = (
            reference.module,
            reference.name,
            reference.node,
        )
        base = prefix + self.keyword_string(module, router, "prefix")
        router_guard = self.dependencies_guard(module, router)
        tree = self.tree(module)
        for node in ast.walk(tree):
            match node:
                case ast.Call(
                    func=ast.Attribute(value=ast.Name(id=owner), attr=attr)
                ) if owner == variable and attr in UNREADABLE_ROUTER_CALLS:
                    raise PolicySourceError(
                        f"{module}:{node.lineno}: {variable}.{attr}(...) "
                        "cannot be read without running the code"
                    )
        for stmt in tree.body:
            if not isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in stmt.decorator_list:
                match decorator:
                    case ast.Call(
                        func=ast.Attribute(value=ast.Name(id=owner), attr=attr)
                    ) if owner == variable and (
                        attr in ROUTE_DECORATORS or attr == "api_route"
                    ):
                        path = (
                            self.string(module, decorator.args[0])
                            if decorator.args
                            else self.keyword_string(module, decorator, "path")
                        )
                        guard = (
                            router_guard
                            | self.dependencies_guard(module, decorator)
                            | self.parameters_guard(
                                module, stmt.args, frozenset()
                            )
                        )
                        for method in self.methods(module, decorator, attr):
                            yield Route(
                                method=method,
                                path=base + path,
                                authenticated=guard.authenticated,
                                roles=guard.expression(),
                            )

    def methods(
        self, module: str, decorator: ast.Call, attr: str
    ) -> list[str]:
        if attr != "api_route":
            return [ROUTE_DECORATORS[attr]]
        for keyword in decorator.keywords:
            if keyword.arg == "methods" and isinstance(
                keyword.value, ast.List | ast.Tuple | ast.Set
            ):
                return [
                    self.string(module, m).upper() for m in keyword.value.elts
                ]
        raise PolicySourceError(
            f"{module}:{decorator.lineno}: api_route needs a literal methods "
            "list to be read without running the code"
        )

    def app_routes(self) -> ast.expr:
        for node in ast.walk(self.tree("app")):
            match node:
                case ast.Call(func=func, keywords=keywords) if (
                    last_name(func) == "App"
                ):
                    for keyword in keywords:
                        if keyword.arg == "routes":
                            return keyword.value
        raise PolicySourceError("app.py has no App(routes=...)")

    def routes(self) -> list[Route]:
        api_prefix = f"/api/{read_project_name(self.root / 'pyproject.toml')}"
        listing = self.app_routes()
        owner = "app"
        if isinstance(listing, ast.Name):
            reference = self.resolve(owner, listing)
            if not isinstance(reference, ValueReference):
                raise PolicySourceError(
                    f"cannot read App(routes={listing.id})"
                )
            assert isinstance(reference.node, ast.expr)
            owner, listing = reference.module, reference.node
        if not isinstance(listing, ast.List | ast.Tuple):
            raise PolicySourceError("App(routes=...) must be a literal list")
        found: list[Route] = []
        for entry in listing.elts:
            if not (isinstance(entry, ast.Tuple) and len(entry.elts) >= 2):
                raise PolicySourceError(
                    f"{owner}:{entry.lineno}: each route entry must be a "
                    "(router, prefix, ...) tuple"
                )
            router = self.resolve(owner, entry.elts[0])
            if not isinstance(router, ValueReference):
                raise PolicySourceError(
                    f"{owner}:{entry.lineno}: cannot find the router "
                    f"{ast.unparse(entry.elts[0])}"
                )
            found.extend(
                self.router_routes(
                    router, api_prefix + self.string(owner, entry.elts[1])
                )
            )
        return sorted(found, key=lambda r: (r.path, r.method))


def read_routes(root: Path) -> list[Route]:
    return ServiceSource(root).routes()
