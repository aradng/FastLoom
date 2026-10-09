import importlib
import os
from collections.abc import Iterator, Sequence
from pathlib import Path

import libcst as cst
import libcst.matchers as m
from libcst.helpers import (
    get_absolute_module_for_import,
    get_full_name_for_node,
)
from libcst.metadata import FullRepoManager, FullyQualifiedNameProvider
from pydantic import BaseModel, ConfigDict

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
    "add_api_route",
    "add_api_websocket_route",
    "add_route",
    "add_websocket_route",
    "route",
}
SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}


class PolicySourceError(Exception): ...


class Route(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str
    path: str


def one_of(*names: str) -> m.Name:
    return m.Name(m.MatchIfTrue(lambda value: value in names))


def named(*names: str) -> m.BaseMatcherNode:
    return one_of(*names) | m.Attribute(attr=one_of(*names))


def saved(name: str = "value") -> m.SaveMatchedNode:
    return m.SaveMatchedNode(m.DoNotCare(), name)


def first_argument(func: m.BaseMatcherNode) -> m.Call:
    return m.Call(
        func=func, args=[m.Arg(value=saved(), keyword=None), m.ZeroOrMore()]
    )


def keyword(name: str) -> m.Call:
    return m.Call(
        args=[
            m.ZeroOrMore(),
            m.Arg(keyword=m.Name(name), value=saved()),
            m.ZeroOrMore(),
        ]
    )


DEPENDENCY = first_argument(named("Depends", "Security"))
ROUTE_ENTRY = m.Tuple(
    elements=[
        m.Element(saved("router")),
        m.Element(saved("prefix")),
        m.ZeroOrMore(),
    ]
)


def extracted(
    node: cst.CSTNode, matcher: m.BaseMatcherNode
) -> cst.CSTNode | None:
    found = m.extract(node, matcher)
    return found["value"] if found is not None else None


def tail(node: cst.CSTNode) -> str:
    return (get_full_name_for_node(node) or "").rsplit(".", 1)[-1]


def code(node: cst.CSTNode) -> str:
    return cst.Module([]).code_for_node(node)


def python_files(root: Path) -> Iterator[str]:
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = [
            d for d in subdirectories if d not in SKIPPED_DIRS
        ]
        yield from (
            os.path.join(directory, n) for n in names if n.endswith(".py")
        )


class Definition(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    module: str
    name: str
    node: cst.CSTNode | None = None


class External(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str


type Resolved = Definition | External


class ServiceSource:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.api_prefix = (
            f"/api/{read_project_name(self.root / 'pyproject.toml')}"
        )
        self.manager = FullRepoManager(
            str(self.root),
            list(python_files(self.root)),
            {FullyQualifiedNameProvider},
        )
        self.wrappers: dict[str, cst.MetadataWrapper] = {}

    def module_path(self, name: str) -> Path | None:
        base = self.root.joinpath(*name.split("."))
        return next(
            (
                path
                for path in (base.with_suffix(".py"), base / "__init__.py")
                if path.exists()
            ),
            None,
        )

    def wrapper(self, module: str) -> cst.MetadataWrapper:
        if module not in self.wrappers:
            path = self.module_path(module)
            if path is None:
                raise PolicySourceError(
                    f"cannot find module {module} in the repo"
                )
            self.wrappers[module] = self.manager.get_metadata_wrapper_for_path(
                str(path)
            )
        return self.wrappers[module]

    def tree(self, module: str) -> cst.Module:
        return self.wrapper(module).module

    def resolve(self, module: str, node: cst.CSTNode) -> Resolved | None:
        names = self.wrapper(module).resolve(FullyQualifiedNameProvider)
        fqn = min((q.name for q in names.get(node, ())), default=None)
        return self.locate(fqn) if fqn is not None else None

    def locate(self, fqn: str) -> Resolved:
        parts = fqn.split(".")
        end = next(
            (
                end
                for end in range(len(parts), 0, -1)
                if self.module_path(".".join(parts[:end])) is not None
            ),
            0,
        )
        if end == 0:
            return External(name=fqn)
        found: Resolved = Definition(
            module=".".join(parts[:end]), name=parts[end - 1]
        )
        for index, name in enumerate(parts[end:], start=end):
            match found:
                case Definition(node=None):
                    statements = self.tree(found.module).body
                case Definition(
                    node=cst.ClassDef(body=cst.IndentedBlock() as body)
                ):
                    statements = body.body
                case External():
                    return External(
                        name=".".join([found.name, *parts[index:]])
                    )
                case _:
                    return External(name=fqn)
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
        found: Resolved = External(name=f"{module}.{name}")
        for stmt in statements:
            if m.matches(stmt, definition):
                found = Definition(module=module, name=name, node=stmt)
            elif (value := extracted(stmt, assignment)) is not None:
                found = Definition(module=module, name=name, node=value)
            for imported in m.findall(stmt, m.ImportFrom()):
                assert isinstance(imported, cst.ImportFrom)
                if isinstance(imported.names, cst.ImportStar):
                    continue
                for alias in imported.names:
                    if (alias.evaluated_alias or alias.evaluated_name) == name:
                        base = get_absolute_module_for_import(module, imported)
                        found = self.locate(f"{base}.{alias.evaluated_name}")
        return found

    def string(self, module: str, node: cst.CSTNode) -> str:
        if isinstance(node, cst.SimpleString | cst.ConcatenatedString):
            value = node.evaluated_value
            if isinstance(value, str):
                return value
        if m.matches(node, m.FormattedString()):
            raise PolicySourceError(
                f"{module}: the f-string {code(node)} cannot be read without "
                "running the code"
            )
        match self.resolve(module, node):
            case Definition(module=owner, node=cst.BaseExpression() as value):
                return self.string(owner, value)
            case External(name=fqn):
                owner, _, attribute = fqn.rpartition(".")
                try:
                    value = getattr(importlib.import_module(owner), attribute)
                except (ImportError, AttributeError, ValueError) as e:
                    raise PolicySourceError(
                        f"{module}: cannot read {fqn}"
                    ) from e
                if isinstance(value, str):
                    return str(value)
        raise PolicySourceError(
            f"{module}: cannot read {code(node)} as a string without running "
            "the code"
        )

    def keyword_string(self, module: str, call: cst.Call, name: str) -> str:
        value = extracted(call, keyword(name))
        return self.string(module, value) if value is not None else ""

    def internal(self, module: str, call: cst.Call) -> bool:
        listing = extracted(call, keyword("dependencies"))
        if listing is None:
            return False
        if not m.matches(listing, m.List() | m.Tuple()):
            raise PolicySourceError(
                f"{module}: dependencies must be a literal list to be read "
                "without running the code"
            )
        return any(
            tail(dependency) == "reject_external"
            for found in m.findall(listing, DEPENDENCY)
            if (dependency := extracted(found, DEPENDENCY)) is not None
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

    def router(self, module: str, node: cst.CSTNode) -> Definition:
        router = self.resolve(module, node)
        if not (
            isinstance(router, Definition)
            and m.matches(router.node, m.Call(func=named("APIRouter")))
        ):
            raise PolicySourceError(
                f"{module}: {code(node)} is not an APIRouter(...) the repo "
                "defines"
            )
        return router

    def router_routes(
        self, router: Definition, prefix: str, internal: bool
    ) -> Iterator[Route]:
        call = router.node
        assert isinstance(call, cst.Call)
        module, tree = router.module, self.tree(router.module)
        on_router = m.Attribute(value=m.Name(router.name))
        for node in m.findall(
            tree,
            m.Call(
                func=on_router
                & m.Attribute(attr=one_of(*UNREADABLE_ROUTER_CALLS))
            ),
        ):
            raise PolicySourceError(
                f"{module}: {code(node)} cannot be read without running the "
                "code"
            )
        base = prefix + self.keyword_string(module, call, "prefix")
        internal = internal or self.internal(module, call)
        route_call = m.Call(
            func=on_router
            & m.Attribute(attr=one_of(*ROUTE_DECORATORS, "api_route"))
        )
        for fn in tree.body:
            if not isinstance(fn, cst.FunctionDef):
                continue
            for decorator in fn.decorators:
                route = decorator.decorator
                if not (
                    isinstance(route, cst.Call)
                    and m.matches(route, route_call)
                ):
                    continue
                path = extracted(route, first_argument(m.DoNotCare()))
                if path is None:
                    path = extracted(route, keyword("path"))
                root = (
                    ""
                    if internal or self.internal(module, route)
                    else self.api_prefix
                )
                for method in self.methods(module, route, tail(route.func)):
                    yield Route(
                        method=method,
                        path=root
                        + base
                        + (
                            self.string(module, path)
                            if path is not None
                            else ""
                        ),
                    )
        include = first_argument(
            on_router & m.Attribute(attr=m.Name("include_router"))
        )
        for included in m.findall(tree, include):
            assert isinstance(included, cst.Call)
            child = extracted(included, include)
            assert child is not None
            yield from self.router_routes(
                self.router(module, child),
                base + self.keyword_string(module, included, "prefix"),
                internal or self.internal(module, included),
            )

    def app_listing(
        self, call: cst.Call, name: str
    ) -> tuple[str, Sequence[cst.Element]]:
        owner, listing = "app", extracted(call, keyword(name))
        if listing is None:
            return owner, ()
        if isinstance(listing, cst.Name):
            match self.resolve(owner, listing):
                case Definition(
                    module=module, node=cst.BaseExpression() as value
                ):
                    owner, listing = module, value
        if not isinstance(listing, cst.List | cst.Tuple):
            raise PolicySourceError(f"App({name}=...) must be a literal list")
        return owner, listing.elements

    def mount_path(self, module: str, node: cst.CSTNode) -> str:
        path = self.string(module, node).rstrip("/")
        if not path.startswith(self.api_prefix):
            path = self.api_prefix + path
        return f"{path}/{{path:path}}"

    def routes(self) -> list[Route]:
        app = next(
            iter(m.findall(self.tree("app"), m.Call(func=named("App")))), None
        )
        if not isinstance(app, cst.Call):
            raise PolicySourceError("app.py has no App(...)")
        found: set[Route] = set()
        owner, entries = self.app_listing(app, "routes")
        for element in entries:
            entry = m.extract(element.value, ROUTE_ENTRY)
            if entry is None:
                raise PolicySourceError(
                    f"{owner}: each route entry must be a "
                    "(router, prefix, ...) tuple"
                )
            assert isinstance(entry["router"], cst.CSTNode)
            assert isinstance(entry["prefix"], cst.CSTNode)
            found.update(
                self.router_routes(
                    self.router(owner, entry["router"]),
                    self.string(owner, entry["prefix"]),
                    False,
                )
            )
        owner, mounts = self.app_listing(app, "mounts")
        for element in mounts:
            path = extracted(
                element.value,
                m.Tuple(elements=[m.Element(saved()), m.ZeroOrMore()]),
            )
            if path is None:
                raise PolicySourceError(
                    f"{owner}: each mount must be a (path, app, ...) tuple"
                )
            found.add(Route(method="*", path=self.mount_path(owner, path)))
        return sorted(found, key=lambda r: (r.path, r.method))


def read_routes(root: Path) -> list[Route]:
    return ServiceSource(root).routes()
