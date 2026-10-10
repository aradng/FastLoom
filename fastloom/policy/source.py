import ast
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from http import HTTPMethod
from importlib.util import resolve_name
from pathlib import Path

from fastloom.constants import (
    HEALTHCHECK_PATH,
    KAFKA_SCHEMA_URL,
    MCP_PATH,
    RABBIT_SCHEMA_URL,
    RELOAD_PATH,
    TENANT_SCHEMA_PATH,
    TENANT_SETTINGS_PATH,
)
from fastloom.meta import read_project_name
from fastloom.policy.schemas import PolicySourceError, Route, ordered
from fastloom.settings.base import ProjectSettings

ROUTE_METHODS = {
    method.lower(): method for method in HTTPMethod if method != "CONNECT"
} | {"websocket": HTTPMethod.GET}
UNREADABLE_ROUTER_CALLS = frozenset(
    {
        "add_api_route",
        "add_api_websocket_route",
        "add_route",
        "add_websocket_route",
        "route",
        "websocket_route",
        "mount",
        "host",
    }
)
ROUTER_METHODS = frozenset(
    {
        *ROUTE_METHODS,
        *UNREADABLE_ROUTER_CALLS,
        "api_route",
        "include_router",
    }
)
APP_MODULE = "app"
SETTINGS_MODULE = "settings"
FRAMEWORK_ROUTES = (
    Route(method=HTTPMethod.GET, path=HEALTHCHECK_PATH),
    Route(method=HTTPMethod.GET, path=TENANT_SCHEMA_PATH),
    Route(method=HTTPMethod.GET, path=TENANT_SETTINGS_PATH),
    Route(method=HTTPMethod.POST, path=TENANT_SETTINGS_PATH),
    Route(method=HTTPMethod.GET, path=RELOAD_PATH),
    Route(method=HTTPMethod.GET, path="/docs"),
    Route(method=HTTPMethod.GET, path="/docs/oauth2-redirect"),
    Route(method=HTTPMethod.GET, path="/redoc"),
    Route(method=HTTPMethod.GET, path="/openapi.json"),
)


def broker_docs(url: str) -> tuple[Route, ...]:
    return (
        Route(method=HTTPMethod.GET, path=url),
        Route(method=HTTPMethod.GET, path=f"{url}.json"),
        Route(method=HTTPMethod.GET, path=f"{url}.yaml"),
        Route(method=HTTPMethod.POST, path=f"{url}/try"),
    )


CAPABILITY_ROUTES = {
    "MCPSettings": (Route(method="*", path=MCP_PATH),),
    "RabbitmqSettings": broker_docs(RABBIT_SCHEMA_URL),
    "KafkaSettings": broker_docs(KAFKA_SCHEMA_URL),
}


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


def named(node: ast.expr, name: str) -> bool:
    match node:
        case ast.Name(id=found) | ast.Attribute(attr=found):
            return found == name
    return False


def bound(alias: ast.alias) -> str:
    return alias.name if alias.asname is None else alias.asname


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def argument(call: ast.Call, name: str) -> ast.expr | None:
    return call.args[0] if call.args else keyword(call, name)


def readable(module: str, call: ast.Call) -> ast.Call:
    if any(isinstance(a, ast.Starred) for a in call.args) or any(
        k.arg is None for k in call.keywords
    ):
        raise PolicySourceError(
            f"{module}: {ast.unparse(call)} cannot be read without running "
            "the code"
        )
    return call


def walk(node: ast.AST) -> Iterator[ast.AST]:
    children: Iterable[ast.AST] = (
        node.decorator_list
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        else ast.iter_child_nodes(node)
    )
    for child in children:
        yield child
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
            return [bound(a).partition(".")[0] for a in aliases]
        case ast.ImportFrom(names=aliases):
            return [bound(a) for a in aliases]
    return []


def bindings(node: ast.AST) -> dict[str, list[ast.stmt]]:
    found: dict[str, list[ast.stmt]] = defaultdict(list)
    for statement in statements(node):
        for name in bound_names(statement):
            found[name].append(statement)
    return found


def has_attribute_access(tree: ast.AST, name: str) -> bool:
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
        self.scope = cache(bindings)

    def find(self, module: str) -> Path | None:
        base = self.root.joinpath(*module.split("."))
        paths = (
            [base / "__init__.py", base.with_suffix(".py")] if module else []
        )
        return next((path for path in paths if path.is_file()), None)

    def parse(self, module: str) -> ast.Module:
        if (path := self.file(module)) is None:
            raise PolicySourceError(f"cannot find module {module} in the repo")
        try:
            return ast.parse(path.read_bytes())
        except SyntaxError as e:
            raise PolicySourceError(
                f"{module}: cannot parse line {e.lineno}: {e.msg}"
            ) from e

    def absolute(self, module: str, node: ast.ImportFrom) -> str:
        path = self.file(module)
        package = (
            module
            if path is not None and path.name == "__init__.py"
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
        for node in walk(self.tree(module)):
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
                    case str() as text if attr == "value":
                        return text
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
        if self.file(full) is not None or self.file(name) is None:
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
                    value, ast.List | ast.Tuple
                ) and has_attribute_access(self.tree(module), name):
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
            case [ast.Import(), *_] as imports if all(
                isinstance(i, ast.Import)
                and all(a.asname is None for a in i.names)
                for i in imports
            ):
                return Ref(name)
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

    def methods(self, found: RouterCall) -> list[HTTPMethod]:
        if found.attr != "api_route":
            return [ROUTE_METHODS[found.attr]]
        match keyword(found.call, "methods"):
            case (
                ast.List(elts=elts) | ast.Tuple(elts=elts) | ast.Set(elts=elts)
            ):
                return [self.method(found.module, e) for e in elts]
        raise PolicySourceError(
            f"{found.module}: api_route needs a literal methods list to be "
            "read without running the code"
        )

    def method(self, module: str, node: ast.expr) -> HTTPMethod:
        name = self.string(module, node).upper()
        if name not in HTTPMethod.__members__:
            raise PolicySourceError(f"{module}: {name} is not an HTTP method")
        return HTTPMethod[name]

    def router_routes(
        self, router: Router, prefix: str, chain: tuple[Router, ...] = ()
    ) -> Iterator[Route]:
        if router in chain:
            raise PolicySourceError(
                f"{router.module}: {ast.unparse(router.call)} includes itself"
            )
        call = readable(router.module, router.call)
        base = prefix + self.string(router.module, keyword(call, "prefix"))
        for found in self.registered[router]:
            module, call = found.module, readable(found.module, found.call)
            if found.attr in UNREADABLE_ROUTER_CALLS:
                raise PolicySourceError(
                    f"{module}: {ast.unparse(call)} cannot be read "
                    "without running the code"
                )
            if found.attr == "include_router":
                yield from self.router_routes(
                    self.router(module, self.required(module, call, "router")),
                    base + self.string(module, keyword(call, "prefix")),
                    (*chain, router),
                )
                continue
            path = (
                self.api_prefix
                + base
                + self.string(module, self.required(module, call, "path"))
            )
            for method in self.methods(found):
                yield Route(method=method, path=path)

    def register(self, module: str) -> None:
        for node in walk(self.tree(module)):
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
                            RouterCall(module, node, attr)
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
        if not f"{path}/".startswith(f"{self.api_prefix}/"):
            path = self.api_prefix + path
        return f"{path}/{{path:path}}"

    def capabilities(self) -> set[str]:
        if self.file(SETTINGS_MODULE) is None:
            return set()
        tree = self.tree(SETTINGS_MODULE)
        match self.lookup(SETTINGS_MODULE, tree, "Settings"):
            case Expr(module=owner, node=ast.ClassDef() as settings):
                return self.bases(owner, settings)
        raise PolicySourceError(f"{SETTINGS_MODULE}: Settings is not a class")

    def bases(self, module: str, cls: ast.ClassDef) -> set[str]:
        return set().union(*(self.base(module, b) for b in cls.bases))

    def base(self, module: str, node: ast.expr) -> set[str]:
        match self.evaluate(module, node):
            case Ref(name=name):
                return {name.rpartition(".")[2]}
            case Expr(module=owner, node=ast.ClassDef() as parent):
                return self.bases(owner, parent)
        raise PolicySourceError(
            f"{module}: cannot read the base class {ast.unparse(node)}"
        )

    def framework_routes(self) -> set[Route]:
        capable = self.capabilities()
        return {
            route.model_copy(update={"path": self.api_prefix + route.path})
            for route in (
                *FRAMEWORK_ROUTES,
                *(
                    route
                    for name, routes in CAPABILITY_ROUTES.items()
                    if name in capable
                    for route in routes
                ),
            )
        }

    def routes(self) -> list[Route]:
        tree = self.tree(APP_MODULE)
        try:
            bound = self.lookup(APP_MODULE, tree, "app")
        except PolicySourceError as e:
            raise PolicySourceError("app.py has no App(...)") from e
        match bound:
            case Expr(node=ast.Call(func=func) as app) if named(func, "App"):
                readable(APP_MODULE, app)
            case _:
                raise PolicySourceError("app.py has no App(...)")
        self.registered: dict[Router, list[RouterCall]] = defaultdict(list)
        for module in self.reachable(APP_MODULE, set()):
            self.register(module)
        found = self.framework_routes()
        owner, entries = self.listing(app, "routes")
        for entry in entries:
            match entry:
                case ast.Tuple(elts=[router, prefix, *_]):
                    found.update(
                        self.router_routes(
                            self.router(owner, router),
                            self.string(owner, prefix),
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
