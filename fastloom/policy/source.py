import importlib
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import libcst as cst
import libcst.matchers as m
from libcst.helpers import (
    calculate_module_and_package,
    get_absolute_module_from_package_for_import,
    get_full_name_for_node,
)
from libcst.metadata import FullRepoManager, FullyQualifiedNameProvider

from fastloom.meta import read_project_name
from fastloom.policy.schemas import Route, ordered
from fastloom.settings.base import ProjectSettings

ROUTE_DECORATORS = {
    "get": "GET",
    "put": "PUT",
    "post": "POST",
    "delete": "DELETE",
    "patch": "PATCH",
    "head": "HEAD",
    "options": "OPTIONS",
    "trace": "TRACE",
    "websocket": "GET",
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
    *ROUTE_DECORATORS,
    *UNREADABLE_ROUTER_CALLS,
    "api_route",
    "include_router",
}
SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}
APP_MODULE = "app"
REJECT_EXTERNAL = "fastloom.launcher.depends.reject_external"


class PolicySourceError(Exception): ...


def one_of(*names: str) -> m.Name:
    return m.Name(m.MatchIfTrue(lambda value: value in names))


def named(*names: str) -> m.OneOf[m.Name | m.Attribute]:
    return one_of(*names) | m.Attribute(attr=one_of(*names))


def saved(name: str = "value") -> m.DoNotCareSentinel:
    return m.SaveMatchedNode(m.DoNotCare(), name)


type CallFunc = m.OneOf[m.Name | m.Attribute] | m.DoNotCareSentinel
ANY = m.DoNotCare()


def positional(func: CallFunc = ANY) -> m.Call:
    return m.Call(
        func=func, args=[m.Arg(value=saved(), keyword=None), m.ZeroOrMore()]
    )


def keyword(name: str, func: CallFunc = ANY) -> m.Call:
    return m.Call(
        func=func,
        args=[
            m.ZeroOrMore(),
            m.Arg(keyword=m.Name(name), value=saved()),
            m.ZeroOrMore(),
        ],
    )


def argument(name: str, func: CallFunc = ANY) -> m.OneOf[m.Call]:
    return positional(func) | keyword(name, func)


DEPENDENCY = argument("dependency", named("Depends", "Security"))
APP_ROUTE_ENTRY = m.Tuple(
    elements=[
        m.Element(saved("router")),
        m.Element(saved("prefix")),
        m.ZeroOrMore(),
    ]
)
MOUNT_ENTRY = m.Tuple(elements=[m.Element(saved()), m.ZeroOrMore()])


def captured(
    found: Mapping[str, cst.CSTNode | Sequence[cst.CSTNode]],
    name: str = "value",
) -> cst.CSTNode:
    # a name saved on one node always captures that node, never a sequence
    return cast(cst.CSTNode, found[name])


def extracted(
    node: cst.CSTNode, matcher: m.BaseMatcherNode
) -> cst.CSTNode | None:
    found = m.extract(node, matcher)
    return captured(found) if found is not None else None


def code(node: cst.CSTNode) -> str:
    return cst.Module([]).code_for_node(node)


def python_files(root: Path) -> Iterator[Path]:
    for directory, subdirectories, names in root.walk():
        subdirectories[:] = [
            d for d in subdirectories if d not in SKIPPED_DIRS
        ]
        yield from (directory / n for n in names if n.endswith(".py"))


@dataclass(frozen=True)
class Definition:
    module: str
    name: str
    node: cst.CSTNode | None = None


@dataclass(frozen=True)
class External:
    name: str


@dataclass(frozen=True)
class Unreadable:
    reason: str


type Resolved = Definition | External | Unreadable


@dataclass(frozen=True)
class Router:
    module: str
    name: str
    call: cst.Call


@dataclass(frozen=True)
class RouterCall:
    call: cst.Call
    func: cst.Attribute
    receiver: str
    endpoint: cst.Parameters | cst.BaseExpression | None


class RouterCalls(cst.CSTVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.endpoints: dict[
            cst.Call, cst.Parameters | cst.BaseExpression
        ] = {}
        self.found: list[RouterCall] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        for decorator in node.decorators:
            if isinstance(decorator.decorator, cst.Call):
                self.endpoints[decorator.decorator] = node.params

    def visit_Call(self, node: cst.Call) -> None:
        if isinstance(node.func, cst.Call) and node.args:
            self.endpoints[node.func] = node.args[0].value
        if not (
            isinstance(node.func, cst.Attribute)
            and node.func.attr.value in ROUTER_METHODS
        ):
            return
        receiver = get_full_name_for_node(node.func.value)
        if receiver is not None:
            self.found.append(
                RouterCall(node, node.func, receiver, self.endpoints.get(node))
            )


class ServiceSource:
    def __init__(self, root: Path):
        self.root = root.resolve()
        try:
            project = read_project_name(self.root / "pyproject.toml")
        except (FileNotFoundError, ValueError) as e:
            raise PolicySourceError(e) from e
        self.api_prefix = ProjectSettings(PROJECT_NAME=project).API_PREFIX
        self.paths: dict[str, Path] = {}
        self.packages: dict[str, str] = {}
        self.texts: dict[str, str] = {}
        for path in python_files(self.root):
            module = calculate_module_and_package(str(self.root), str(path))
            self.paths[module.name] = path
            self.packages[module.name] = module.package
            self.texts[module.name] = path.read_text()
        self.manager = FullRepoManager(
            str(self.root),
            [str(p) for p in self.paths.values()],
            {FullyQualifiedNameProvider},
        )
        self.wrappers: dict[str, cst.MetadataWrapper] = {}
        self.located: dict[str, Resolved] = {}
        self.router_calls: dict[str, list[RouterCall]] = {}
        self.callers: dict[str, tuple[set[str], list[str]]] = {}
        self.reject_names = self.aliases(REJECT_EXTERNAL.rpartition(".")[2])

    def wrapper(self, module: str) -> cst.MetadataWrapper:
        if module not in self.wrappers:
            if module not in self.paths:
                raise PolicySourceError(
                    f"cannot find module {module} in the repo"
                )
            try:
                self.wrappers[module] = (
                    self.manager.get_metadata_wrapper_for_path(
                        str(self.paths[module])
                    )
                )
            except cst.ParserSyntaxError as e:
                raise PolicySourceError(
                    f"{module}: cannot parse line {e.raw_line}: {e.message}"
                ) from e
        return self.wrappers[module]

    def tree(self, module: str) -> cst.Module:
        return self.wrapper(module).module

    def lookup(self, module: str, node: cst.CSTNode) -> Resolved | None:
        names = self.wrapper(module).resolve(FullyQualifiedNameProvider)
        fqn = min((q.name for q in names.get(node, ())), default=None)
        return self.locate(fqn) if fqn is not None else None

    def resolve(
        self, module: str, node: cst.CSTNode
    ) -> Definition | External | None:
        found = self.lookup(module, node)
        if isinstance(found, Unreadable):
            raise PolicySourceError(found.reason)
        return found

    def locate(self, fqn: str) -> Resolved:
        if fqn not in self.located:
            self.located[fqn] = self.find(fqn)
        return self.located[fqn]

    def find(self, fqn: str) -> Resolved:
        parts = fqn.split(".")
        end = next(
            (
                end
                for end in range(len(parts), 0, -1)
                if ".".join(parts[:end]) in self.paths
            ),
            0,
        )
        if end == 0:
            return External(fqn)
        found: Resolved = Definition(".".join(parts[:end]), parts[end - 1])
        for index, name in enumerate(parts[end:], start=end):
            match found:
                case Definition(node=None):
                    statements = self.tree(found.module).body
                case Definition(
                    node=cst.ClassDef(body=cst.IndentedBlock(body=statements))
                ):
                    pass
                case External():
                    return External(".".join([found.name, *parts[index:]]))
                case Unreadable():
                    return found
                case _:
                    return External(fqn)
            found = self.member(found.module, statements, name)
        return found

    def member(
        self, module: str, statements: Sequence[cst.BaseStatement], name: str
    ) -> Resolved:
        definition = m.FunctionDef(name=m.Name(name)) | m.ClassDef(
            name=m.Name(name)
        )
        assignment = m.SimpleStatementLine(
            body=[
                m.Assign(targets=[m.AssignTarget(m.Name(name))], value=saved())
                | m.AnnAssign(target=m.Name(name), value=saved())
            ]
        )
        mutation = m.AugAssign(target=m.Name(name)) | m.Call(
            func=m.Attribute(
                value=m.Name(name), attr=one_of("append", "extend")
            )
        )
        bindings: list[Resolved] = []
        for stmt in statements:
            if m.matches(stmt, definition):
                bindings.append(Definition(module, name, stmt))
            if isinstance(stmt, cst.FunctionDef | cst.ClassDef):
                continue
            value = extracted(stmt, assignment)
            if isinstance(value, cst.Name | cst.Attribute):
                bindings.append(
                    self.locate(f"{module}.{get_full_name_for_node(value)}")
                )
            elif value is not None:
                bindings.append(Definition(module, name, value))
            if m.findall(stmt, mutation):
                return Unreadable(
                    f"{module}: {name} is changed after it is bound, which "
                    "cannot be read without running the code"
                )
            for node in m.findall(stmt, m.ImportFrom()):
                imported = cst.ensure_type(node, cst.ImportFrom)
                if isinstance(imported.names, cst.ImportStar):
                    continue
                base = get_absolute_module_from_package_for_import(
                    self.packages[module], imported
                )
                bindings += [
                    self.locate(f"{base}.{alias.evaluated_name}")
                    for alias in imported.names
                    if (alias.evaluated_alias or alias.evaluated_name) == name
                ]
        if len(bindings) > 1:
            return Unreadable(
                f"{module}: {name} is bound more than once, which cannot be "
                "read without running the code"
            )
        return bindings[0] if bindings else External(f"{module}.{name}")

    def aliases(self, name: str) -> set[str]:
        names = {name}
        while True:
            alternatives = "|".join(names)
            imported = re.compile(rf"\b(?:{alternatives})\s+as\s+(\w+)")
            assigned = re.compile(
                rf"^(\w+)\s*=\s*(?:\w+\.)*(?:{alternatives})\s*$", re.M
            )
            found = {
                alias
                for text in self.texts.values()
                for pattern in (imported, assigned)
                for alias in pattern.findall(text)
            }
            if found <= names:
                return names
            names |= found

    def external(self, module: str, fqn: str) -> object:
        parts = fqn.split(".")
        for end in range(len(parts) - 1, 0, -1):
            try:
                value: object = importlib.import_module(".".join(parts[:end]))
            except ImportError:
                continue
            try:
                for attribute in parts[end:]:
                    value = getattr(value, attribute)
            except AttributeError as e:
                raise PolicySourceError(f"{module}: cannot read {fqn}") from e
            return value
        raise PolicySourceError(f"{module}: cannot import {fqn}")

    def string(self, module: str, node: cst.CSTNode) -> str:
        if isinstance(node, cst.SimpleString | cst.ConcatenatedString):
            evaluated = node.evaluated_value
            if isinstance(evaluated, str):
                return evaluated
        if isinstance(node, cst.FormattedString):
            raise PolicySourceError(
                f"{module}: the f-string {code(node)} cannot be read without "
                "running the code"
            )
        match self.resolve(module, node):
            case Definition(module=owner, node=cst.BaseExpression() as value):
                return self.string(owner, value)
            case External(name=fqn):
                found = self.external(module, fqn)
                if isinstance(found, str):
                    return str.__str__(found)
        raise PolicySourceError(
            f"{module}: cannot read {code(node)} as a string without running "
            "the code"
        )

    def keyword_string(self, module: str, call: cst.Call, name: str) -> str:
        value = extracted(call, keyword(name))
        return self.string(module, value) if value is not None else ""

    def argument(self, module: str, call: cst.Call, name: str) -> cst.CSTNode:
        value = extracted(call, argument(name))
        if value is None:
            raise PolicySourceError(
                f"{module}: {code(call)} has no {name} to read"
            )
        return value

    def rejects_external(self, module: str, node: cst.CSTNode) -> bool:
        return any(
            name in self.texts[module] for name in self.reject_names
        ) and any(
            self.lookup(module, captured(found)) == External(REJECT_EXTERNAL)
            for found in m.extractall(node, DEPENDENCY)
        )

    def internal(self, module: str, call: cst.Call) -> bool:
        listing = extracted(call, keyword("dependencies"))
        if listing is None:
            return False
        if not isinstance(listing, cst.List | cst.Tuple):
            raise PolicySourceError(
                f"{module}: dependencies must be a literal list to be read "
                "without running the code"
            )
        return self.rejects_external(module, listing)

    def endpoint_internal(self, module: str, route: RouterCall) -> bool:
        match route.endpoint:
            case cst.Parameters() as params:
                return self.rejects_external(module, params)
            case cst.BaseExpression() as function:
                match self.resolve(module, function):
                    case Definition(
                        module=owner, node=cst.FunctionDef(params=params)
                    ):
                        return self.rejects_external(owner, params)
        raise PolicySourceError(
            f"{module}: cannot find the endpoint {code(route.call)} registers"
        )

    def methods(self, module: str, route: cst.Call, attr: str) -> list[str]:
        if attr != "api_route":
            return [ROUTE_DECORATORS[attr]]
        listing = extracted(route, keyword("methods"))
        if not isinstance(listing, cst.List | cst.Tuple | cst.Set):
            raise PolicySourceError(
                f"{module}: api_route needs a literal methods list to be read "
                "without running the code"
            )
        return [self.string(module, e.value).upper() for e in listing.elements]

    def router(self, module: str, node: cst.CSTNode) -> Router:
        match self.resolve(module, node):
            case Definition(
                module=owner, name=name, node=cst.Call() as call
            ) if m.matches(call, m.Call(func=named("APIRouter"))):
                return Router(owner, name, call)
        raise PolicySourceError(
            f"{module}: {code(node)} is not an APIRouter(...) the repo defines"
        )

    def module_calls(self, module: str) -> list[RouterCall]:
        if module not in self.router_calls:
            visitor = RouterCalls()
            self.tree(module).visit(visitor)
            self.router_calls[module] = visitor.found
        return self.router_calls[module]

    def calls(self, router: Router) -> Iterator[tuple[str, RouterCall]]:
        if router.name not in self.callers:
            names = self.aliases(router.name)
            receiver = re.compile(
                rf"\b(?:{'|'.join(names)})\s*\.\s*"
                rf"(?:{'|'.join(ROUTER_METHODS)})\s*\("
            )
            self.callers[router.name] = (
                names,
                [
                    module
                    for module, text in self.texts.items()
                    if receiver.search(text)
                ],
            )
        names, modules = self.callers[router.name]
        for module in modules:
            for found in self.module_calls(module):
                if found.receiver.rpartition(".")[2] not in names:
                    continue
                target: Resolved | None = self.locate(
                    f"{module}.{found.receiver}"
                )
                if not isinstance(target, Definition):
                    target = self.lookup(module, found.func.value)
                match target:
                    case Definition(node=node) if node is router.call:
                        yield module, found

    def router_routes(
        self, router: Router, prefix: str, internal: bool
    ) -> Iterator[Route]:
        base = prefix + self.keyword_string(
            router.module, router.call, "prefix"
        )
        internal = internal or self.internal(router.module, router.call)
        for module, found in self.calls(router):
            call, attr = found.call, found.func.attr.value
            if attr in UNREADABLE_ROUTER_CALLS:
                raise PolicySourceError(
                    f"{module}: {code(call)} cannot be read without running "
                    "the code"
                )
            if attr == "include_router":
                yield from self.router_routes(
                    self.router(module, self.argument(module, call, "router")),
                    base + self.keyword_string(module, call, "prefix"),
                    internal or self.internal(module, call),
                )
                continue
            bare = (
                internal
                or self.internal(module, call)
                or self.endpoint_internal(module, found)
            )
            path = (
                ("" if bare else self.api_prefix)
                + base
                + self.string(module, self.argument(module, call, "path"))
            )
            for method in self.methods(module, call, attr):
                yield Route(method, path)

    def app_listing(
        self, app: cst.Call, name: str
    ) -> tuple[str, Sequence[cst.BaseElement]]:
        owner, listing = APP_MODULE, extracted(app, keyword(name))
        if listing is None:
            return owner, ()
        match self.resolve(owner, listing):
            case Definition(module=module, node=cst.BaseExpression() as value):
                owner, listing = module, value
        if not isinstance(listing, cst.List | cst.Tuple):
            raise PolicySourceError(f"App({name}=...) must be a literal list")
        return owner, listing.elements

    def mount_path(self, module: str, node: cst.CSTNode) -> str:
        path = self.string(module, node).rstrip("/")
        if not (
            path == self.api_prefix or path.startswith(f"{self.api_prefix}/")
        ):
            path = self.api_prefix + path
        return f"{path}/{{path:path}}"

    def routes(self) -> list[Route]:
        apps = m.findall(self.tree(APP_MODULE), m.Call(func=named("App")))
        if not apps:
            raise PolicySourceError("app.py has no App(...)")
        app = cst.ensure_type(apps[0], cst.Call)
        found: set[Route] = set()
        owner, entries = self.app_listing(app, "routes")
        for element in entries:
            entry = m.extract(element.value, APP_ROUTE_ENTRY)
            if entry is None:
                raise PolicySourceError(
                    f"{owner}: each route entry must be a "
                    "(router, prefix, ...) tuple"
                )
            found.update(
                self.router_routes(
                    self.router(owner, captured(entry, "router")),
                    self.string(owner, captured(entry, "prefix")),
                    internal=False,
                )
            )
        owner, mounts = self.app_listing(app, "mounts")
        for element in mounts:
            path = extracted(element.value, MOUNT_ENTRY)
            if path is None:
                raise PolicySourceError(
                    f"{owner}: each mount must be a (path, app, ...) tuple"
                )
            found.add(Route("*", self.mount_path(owner, path)))
        return ordered(found)
