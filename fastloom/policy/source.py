import ast
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from http import HTTPMethod
from importlib.util import resolve_name
from pathlib import Path

from fastloom.meta import read_project_name
from fastloom.policy.schemas import Route, ordered
from fastloom.settings.base import ProjectSettings

ROUTE_METHODS = {method.lower(): method for method in HTTPMethod} | {
    "websocket": HTTPMethod.GET
}
UNREADABLE_ROUTER_CALLS = {
    "add_api_route",
    "add_api_websocket_route",
    "add_route",
    "add_websocket_route",
    "route",
    "websocket_route",
    "mount",
    "host",
}
ROUTER_METHODS = {
    *ROUTE_METHODS,
    *UNREADABLE_ROUTER_CALLS,
    "api_route",
    "include_router",
}
APP_MODULE = "app"
REJECT_EXTERNAL = "fastloom.launcher.depends.reject_external"


class PolicySourceError(Exception): ...


@dataclass(frozen=True)
class Ref:
    name: str


@dataclass(frozen=True)
class Expr:
    module: str
    node: ast.AST


@dataclass(frozen=True)
class Router:
    module: str
    call: ast.Call


type Value = str | Ref | Expr | Router


@dataclass(frozen=True)
class RouterCall:
    module: str
    call: ast.Call
    attr: str
    parent: ast.AST


def named(node: ast.expr, *names: str) -> bool:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name in names
    return False


def bound(alias: ast.alias) -> str:
    return alias.name if alias.asname is None else alias.asname


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def argument(call: ast.Call, name: str) -> ast.expr | None:
    return call.args[0] if call.args else keyword(call, name)


def walk(node: ast.AST) -> Iterator[tuple[ast.AST, ast.AST]]:
    children: Iterable[ast.AST] = (
        node.decorator_list
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        else ast.iter_child_nodes(node)
    )
    for child in children:
        yield child, node
        yield from walk(child)


def statements(node: ast.AST) -> Iterator[ast.stmt]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            yield child
        if not isinstance(
            child,
            ast.expr | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        ):
            yield from statements(child)


def bound_names(statement: ast.stmt) -> list[str]:
    match statement:
        case ast.Assign(targets=targets):
            return [
                n.id
                for target in targets
                for n in ast.walk(target)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
            ]
        case (
            ast.AugAssign(target=ast.Name(id=name))
            | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr())
            | ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
        ):
            return [name]
        case ast.Import(names=aliases):
            return [
                a.name.partition(".")[0] if a.asname is None else a.asname
                for a in aliases
            ]
        case ast.ImportFrom(names=aliases):
            return [bound(a) for a in aliases]
    return []


def mutated(tree: ast.AST, name: str) -> bool:
    return any(
        isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == name
        for n in ast.walk(tree)
    )


class ServiceSource:
    def __init__(self, root: Path):
        self.root = root.resolve()
        try:
            project = read_project_name(self.root / "pyproject.toml")
        except (FileNotFoundError, ValueError) as e:
            raise PolicySourceError(e) from e
        self.api_prefix = ProjectSettings(PROJECT_NAME=project).API_PREFIX
        self.file = cache(self.find)
        self.tree = cache(self.parse)
        self.scope = cache(self.bindings)
        self.registered: dict[Router, list[RouterCall]] = defaultdict(list)

    def find(self, module: str) -> Path | None:
        base = self.root.joinpath(*module.split("."))
        paths = (
            [base / "__init__.py", base.with_suffix(".py")] if module else []
        )
        return next((path for path in paths if path.is_file()), None)

    def parse(self, module: str) -> ast.Module:
        try:
            path = self.file(module)
            if path is None:
                raise PolicySourceError(
                    f"cannot find module {module} in the repo"
                )
            return ast.parse(path.read_text())
        except SyntaxError as e:
            raise PolicySourceError(
                f"{module}: cannot parse line {e.lineno}: {e.msg}"
            ) from e

    def bindings(self, node: ast.AST) -> dict[str, list[ast.stmt]]:
        found: dict[str, list[ast.stmt]] = defaultdict(list)
        for statement in statements(node):
            for name in bound_names(statement):
                found[name].append(statement)
        return found

    def absolute(self, module: str, node: ast.ImportFrom) -> str:
        package = (
            module
            if str(self.file(module)).endswith("__init__.py")
            else module.rpartition(".")[0]
        )
        try:
            return resolve_name(
                "." * node.level + (node.module or ""), package
            )
        except ImportError as e:
            raise PolicySourceError(
                f"{module}: cannot resolve {ast.unparse(node)}"
            ) from e

    def imports(self, module: str) -> Iterator[str]:
        yield module.rpartition(".")[0]
        for node, _ in walk(self.tree(module)):
            match node:
                case ast.Import(names=aliases):
                    yield from (a.name for a in aliases)
                case ast.ImportFrom(names=aliases):
                    base = self.absolute(module, node)
                    yield base
                    yield from (f"{base}.{a.name}" for a in aliases)

    def reachable(self, module: str, seen: set[str]) -> set[str]:
        if module not in seen and self.file(module) is not None:
            seen.add(module)
            for imported in self.imports(module):
                self.reachable(imported, seen)
        return seen

    def evaluate(self, module: str, node: ast.AST) -> Value:
        match node:
            case ast.Constant(value=str() as value):
                return value
            case ast.JoinedStr():
                raise PolicySourceError(
                    f"{module}: the f-string {ast.unparse(node)} "
                    "cannot be read without running the code"
                )
            case ast.Name(id=name):
                return self.lookup(module, self.tree(module), name)
            case ast.Attribute(value=value, attr=attr):
                match self.evaluate(module, value):
                    case Ref(name=name):
                        return self.attribute(name, attr)
                    case Expr(module=owner, node=ast.ClassDef() as body):
                        return self.lookup(owner, body, attr)
                raise PolicySourceError(
                    f"{module}: cannot read {ast.unparse(node)}"
                )
            case ast.Call(func=func) if named(func, "APIRouter"):
                return Router(module, node)
        return Expr(module, node)

    def attribute(self, name: str, attr: str) -> Value:
        full = f"{name}.{attr}"
        if self.file(full) or not self.file(name):
            return Ref(full)
        return self.lookup(name, self.tree(name), attr)

    def lookup(self, module: str, scope: ast.AST, name: str) -> Value:
        match self.scope(scope).get(name, []):
            case [ast.Import(names=aliases)]:
                return Ref(
                    next((a.name for a in aliases if a.asname == name), name)
                )
            case [ast.ImportFrom(names=aliases) as imported]:
                return self.attribute(
                    self.absolute(module, imported),
                    next(a.name for a in aliases if bound(a) == name),
                )
            case [
                ast.Assign(value=value)
                | ast.AnnAssign(value=ast.expr() as value)
            ]:
                if isinstance(
                    value, ast.List | ast.Tuple | ast.Set
                ) and mutated(self.tree(module), name):
                    raise PolicySourceError(
                        f"{module}: {name} is changed after it is bound, "
                        "which cannot be read without running the code"
                    )
                return self.evaluate(module, value)
            case [
                ast.FunctionDef()
                | ast.AsyncFunctionDef()
                | ast.ClassDef() as definition
            ]:
                return Expr(module, definition)
            case [_, _, *_]:
                raise PolicySourceError(
                    f"{module}: {name} is bound more than once, which "
                    "cannot be read without running the code"
                )
        raise PolicySourceError(f"{module}: cannot find {name}")

    def string(self, module: str, node: ast.expr | None) -> str:
        if node is None:
            return ""
        match self.evaluate(module, node):
            case str() as value:
                return value
        raise PolicySourceError(
            f"{module}: cannot read {ast.unparse(node)} as a string "
            "the repo defines without running the code"
        )

    def router(self, module: str, node: ast.expr) -> Router:
        match self.evaluate(module, node):
            case Router() as router:
                return router
        raise PolicySourceError(
            f"{module}: {ast.unparse(node)} is not an APIRouter(...) "
            "the repo defines"
        )

    def required(self, module: str, call: ast.Call, name: str) -> ast.expr:
        if (value := argument(call, name)) is not None:
            return value
        raise PolicySourceError(
            f"{module}: {ast.unparse(call)} has no {name} to read"
        )

    def rejecting(self, module: str, dependency: ast.expr) -> bool:
        try:
            return self.evaluate(module, dependency) == Ref(REJECT_EXTERNAL)
        except PolicySourceError:
            return False

    def rejects_external(self, module: str, node: ast.AST) -> bool:
        return any(
            self.rejecting(module, dependency)
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and named(call.func, "Depends", "Security")
            and (dependency := argument(call, "dependency")) is not None
        )

    def internal(self, module: str, call: ast.Call) -> bool:
        match keyword(call, "dependencies"):
            case None:
                return False
            case ast.List() | ast.Tuple() as listing:
                return self.rejects_external(module, listing)
        raise PolicySourceError(
            f"{module}: dependencies must be a literal list to be read "
            "without running the code"
        )

    def endpoint_internal(self, found: RouterCall) -> bool:
        match found.parent:
            case ast.FunctionDef(args=args) | ast.AsyncFunctionDef(args=args):
                return self.rejects_external(found.module, args)
            case ast.Call(func=func, args=[endpoint, *_]) if (
                func is found.call
            ):
                match self.evaluate(found.module, endpoint):
                    case Expr(
                        module=owner,
                        node=ast.FunctionDef(args=args)
                        | ast.AsyncFunctionDef(args=args),
                    ):
                        return self.rejects_external(owner, args)
        raise PolicySourceError(
            f"{found.module}: cannot find the endpoint "
            f"{ast.unparse(found.call)} registers"
        )

    def methods(self, found: RouterCall) -> list[HTTPMethod]:
        if found.attr != "api_route":
            return [ROUTE_METHODS[found.attr]]
        match keyword(found.call, "methods"):
            case (
                ast.List(elts=elts) | ast.Tuple(elts=elts) | ast.Set(elts=elts)
            ):
                return [
                    HTTPMethod(self.string(found.module, e).upper())
                    for e in elts
                ]
        raise PolicySourceError(
            f"{found.module}: api_route needs a literal methods list to be "
            "read without running the code"
        )

    def router_routes(
        self, router: Router, prefix: str, internal: bool
    ) -> Iterator[Route]:
        base = prefix + self.string(
            router.module, keyword(router.call, "prefix")
        )
        internal = internal or self.internal(router.module, router.call)
        for found in self.registered[router]:
            module, call = found.module, found.call
            if found.attr in UNREADABLE_ROUTER_CALLS:
                raise PolicySourceError(
                    f"{module}: {ast.unparse(call)} cannot be read "
                    "without running the code"
                )
            if found.attr == "include_router":
                yield from self.router_routes(
                    self.router(module, self.required(module, call, "router")),
                    base + self.string(module, keyword(call, "prefix")),
                    internal or self.internal(module, call),
                )
                continue
            bare = (
                internal
                or self.internal(module, call)
                or self.endpoint_internal(found)
            )
            path = (
                ("" if bare else self.api_prefix)
                + base
                + self.string(module, self.required(module, call, "path"))
            )
            for method in self.methods(found):
                yield Route(method=method, path=path)

    def register(self, module: str) -> None:
        for node, parent in walk(self.tree(module)):
            match node:
                case ast.Call(
                    func=ast.Attribute(value=receiver, attr=attr)
                ) if attr in ROUTER_METHODS:
                    try:
                        router = self.evaluate(module, receiver)
                    except PolicySourceError:
                        continue
                    if isinstance(router, Router):
                        self.registered[router].append(
                            RouterCall(module, node, attr, parent)
                        )

    def listing(self, app: ast.Call, name: str) -> tuple[str, list[ast.expr]]:
        node = keyword(app, name)
        if node is None:
            return APP_MODULE, []
        match self.evaluate(APP_MODULE, node):
            case Expr(
                module=owner, node=ast.List(elts=elts) | ast.Tuple(elts=elts)
            ):
                return owner, elts
        raise PolicySourceError(f"App({name}=...) must be a literal list")

    def mount_path(self, module: str, node: ast.expr) -> str:
        path = self.string(module, node).rstrip("/")
        if not (
            path == self.api_prefix or path.startswith(f"{self.api_prefix}/")
        ):
            path = self.api_prefix + path
        return f"{path}/{{path:path}}"

    def routes(self) -> list[Route]:
        app = next(
            (
                node
                for node, _ in walk(self.tree(APP_MODULE))
                if isinstance(node, ast.Call) and named(node.func, "App")
            ),
            None,
        )
        if app is None:
            raise PolicySourceError("app.py has no App(...)")
        for module in self.reachable(APP_MODULE, set()):
            self.register(module)
        found: set[Route] = set()
        owner, entries = self.listing(app, "routes")
        for entry in entries:
            match entry:
                case ast.Tuple(elts=[router, prefix, *_]):
                    found.update(
                        self.router_routes(
                            self.router(owner, router),
                            self.string(owner, prefix),
                            internal=False,
                        )
                    )
                case _:
                    raise PolicySourceError(
                        f"{owner}: each route entry must be a "
                        "(router, prefix, ...) tuple"
                    )
        owner, mounts = self.listing(app, "mounts")
        for mount in mounts:
            match mount:
                case ast.Tuple(elts=[path, *_]):
                    found.add(
                        Route(method="*", path=self.mount_path(owner, path))
                    )
                case _:
                    raise PolicySourceError(
                        f"{owner}: each mount must be a (path, app, ...) tuple"
                    )
        return ordered(found)
