"""Structural guard: every `Resource` subclass under `src/hassette/` reaches `mark_ready()`.

A resource that never calls `mark_ready()` leaves its `ready_event` unset, so whatever waits on it
(startup, a parent's child wait, a dependency wait) hangs with no error. This test scans the source
with `ast`, finds every class that subclasses `Resource` directly or through another class in the
scan, and requires that the class body, or the body of a base class in the scan, contains a
`mark_ready(...)` call.

Exemptions:

- `ALLOWLIST` names classes marked ready by their parent or by the framework, each with a reason.
- `# structural: ignore[mark-ready]` on the `class` line exempts a one-off.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_DIR = SRC_ROOT / "hassette"

RESOURCE_ROOT = "hassette.resources.base.Resource"
MARK_READY_NAME = "hassette.resources.lifecycle.mark_ready"
IGNORE_MARKER = "# structural: ignore[mark-ready]"

ALLOWLIST: dict[str, str] = {
    "hassette.app.app.App": "AppLifecycleService marks each app instance ready after its initialize() returns",
    "hassette.app.app.AppSync": "AppLifecycleService marks each app instance ready after its initialize() returns",
    "hassette.core.core.Hassette": "sets its own ready_event directly once the database phase of startup completes",
    "hassette.testing._harness_resources.HarnessHassette": "inherits Hassette's direct ready_event.set()",
    "hassette.resources.service.Service": "abstract base; each concrete Service subclass marks itself ready",
    "hassette.bus.sync_events.BusSyncEventShortcuts": "intermediate base; BusSyncFacade supplies the lifecycle hooks",
    "hassette.scheduler.sync_convenience.SchedulerSyncConvenience": (
        "intermediate base; SchedulerSyncFacade supplies the lifecycle hooks"
    ),
}


@dataclass(frozen=True)
class ClassInfo:
    """One class definition found in the scan."""

    qualname: str
    path: Path
    lineno: int
    bases: tuple[str, ...]
    call_names: frozenset[str]
    ignored: bool


@dataclass
class ModuleInfo:
    """Import aliases and top-level classes of one module."""

    aliases: dict[str, str] = field(default_factory=dict)
    classes: dict[str, ClassInfo] = field(default_factory=dict)


def module_name(path: Path, src_root: Path) -> str:
    parts = list(path.relative_to(src_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def import_aliases(tree: ast.Module, module: str, is_package: bool) -> dict[str, str]:
    """Map each name bound by an import in ``tree`` to the dotted name it refers to."""
    package = module if is_package else module.rpartition(".")[0]
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    root = alias.name.split(".")[0]
                    aliases[root] = root
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                if node.level > 1:
                    anchor = anchor[: -(node.level - 1)]
                base = ".".join([*anchor, base]) if base else ".".join(anchor)
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{base}.{alias.name}"
    return aliases


def dotted_name(expr: ast.expr, aliases: dict[str, str], module: str, local_names: set[str]) -> str | None:
    """Resolve a base-class or call expression to a dotted name, or None if it isn't a plain reference."""
    if isinstance(expr, ast.Subscript):
        return dotted_name(expr.value, aliases, module, local_names)
    if isinstance(expr, ast.Name):
        if expr.id in local_names:
            return f"{module}.{expr.id}"
        return aliases.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        base = dotted_name(expr.value, aliases, module, local_names)
        return None if base is None else f"{base}.{expr.attr}"
    return None


def scan_source(source: str, module: str, path: Path, is_package: bool = False) -> ModuleInfo:
    """Collect import aliases and top-level class definitions from one module's source."""
    tree = ast.parse(source)
    lines = source.splitlines()
    info = ModuleInfo(aliases=import_aliases(tree, module, is_package))
    local_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = tuple(
            name for base in node.bases if (name := dotted_name(base, info.aliases, module, local_names)) is not None
        )
        call_names = frozenset(
            name
            for sub in ast.walk(node)
            if isinstance(sub, ast.Call)
            and (name := dotted_name(sub.func, info.aliases, module, local_names)) is not None
        )
        info.classes[node.name] = ClassInfo(
            qualname=f"{module}.{node.name}",
            path=path,
            lineno=node.lineno,
            bases=bases,
            call_names=call_names,
            ignored=IGNORE_MARKER in lines[node.lineno - 1],
        )
    return info


class ClassIndex:
    """Every class in the scanned modules, with names resolved through re-exports."""

    def __init__(self, modules: dict[str, ModuleInfo]) -> None:
        self.modules = modules
        self.classes = {cls.qualname: cls for mod in modules.values() for cls in mod.classes.values()}

    def resolve(self, name: str, seen: frozenset[str] = frozenset()) -> str:
        """Follow re-exports (``from x import Y`` in a package ``__init__``) to the defining module."""
        if name in self.classes or name in seen:
            return name
        module, _, attr = name.rpartition(".")
        target = self.modules.get(module)
        if target is None or attr not in target.aliases:
            return name
        return self.resolve(target.aliases[attr], seen | {name})

    def ancestors(self, cls: ClassInfo) -> list[ClassInfo]:
        """All scanned ancestors of ``cls``, nearest first."""
        found: list[ClassInfo] = []
        pending = [self.resolve(base) for base in cls.bases]
        while pending:
            name = pending.pop(0)
            parent = self.classes.get(name)
            if parent is None or parent in found:
                continue
            found.append(parent)
            pending.extend(self.resolve(base) for base in parent.bases)
        return found

    def calls_mark_ready(self, cls: ClassInfo) -> bool:
        return any(self.resolve(name) == MARK_READY_NAME for name in cls.call_names)

    def resource_subclasses(self) -> list[ClassInfo]:
        return [
            cls
            for cls in self.classes.values()
            if cls.qualname != RESOURCE_ROOT and any(a.qualname == RESOURCE_ROOT for a in self.ancestors(cls))
        ]


def missing_mark_ready(index: ClassIndex, allowlist: dict[str, str]) -> list[str]:
    """Describe each Resource subclass with no reachable ``mark_ready()`` call and no exemption."""
    missing: list[str] = []
    for cls in index.resource_subclasses():
        if cls.ignored or cls.qualname in allowlist:
            continue
        if any(index.calls_mark_ready(c) for c in (cls, *index.ancestors(cls))):
            continue
        rel = cls.path.relative_to(REPO_ROOT) if cls.path.is_relative_to(REPO_ROOT) else cls.path
        missing.append(f"{cls.qualname} ({rel}:{cls.lineno})")
    return sorted(missing)


def scan_package(package_dir: Path, src_root: Path) -> dict[str, ModuleInfo]:
    modules: dict[str, ModuleInfo] = {}
    for path in sorted(package_dir.rglob("*.py")):
        module = module_name(path, src_root)
        modules[module] = scan_source(path.read_text(encoding="utf-8"), module, path, path.name == "__init__.py")
    return modules


@pytest.fixture(scope="module")
def real_modules() -> dict[str, ModuleInfo]:
    return scan_package(PACKAGE_DIR, SRC_ROOT)


def test_every_resource_subclass_reaches_mark_ready(real_modules: dict[str, ModuleInfo]) -> None:
    missing = missing_mark_ready(ClassIndex(real_modules), ALLOWLIST)
    assert not missing, (
        "These Resource subclasses never call mark_ready(), so startup would hang waiting on them. "
        "Call mark_ready(self, reason=...) from an initialization hook, add the class to ALLOWLIST "
        f"with a reason, or mark the class line with `{IGNORE_MARKER}`:\n  " + "\n  ".join(missing)
    )


def test_allowlist_entries_carry_reasons_and_exist(real_modules: dict[str, ModuleInfo]) -> None:
    index = ClassIndex(real_modules)
    subclasses = {cls.qualname for cls in index.resource_subclasses()}
    assert all(reason.strip() for reason in ALLOWLIST.values())
    stale = sorted(set(ALLOWLIST) - subclasses)
    assert not stale, f"ALLOWLIST names classes that are no longer Resource subclasses: {stale}"


def check_synthetic(real_modules: dict[str, ModuleInfo], source: str) -> list[str]:
    """Run the check on ``source`` as a module scanned alongside the real package."""
    module = "hassette.synthetic_resource"
    modules = {**real_modules, module: scan_source(source, module, Path("synthetic_resource.py"))}
    return [entry for entry in missing_mark_ready(ClassIndex(modules), ALLOWLIST) if module in entry]


def test_flags_resource_without_mark_ready(real_modules: dict[str, ModuleInfo]) -> None:
    source = """
from hassette.resources.base import Resource

class Forgetful(Resource):
    async def on_initialize(self) -> None:
        pass
"""
    assert check_synthetic(real_modules, source) == ["hassette.synthetic_resource.Forgetful (synthetic_resource.py:4)"]


def test_flags_indirect_subclass_through_module_alias(real_modules: dict[str, ModuleInfo]) -> None:
    source = """
from hassette.resources import service as svc

class Forgetful(svc.Service):
    async def serve(self) -> None:
        pass
"""
    assert check_synthetic(real_modules, source) == ["hassette.synthetic_resource.Forgetful (synthetic_resource.py:4)"]


def test_accepts_mark_ready_in_helper_method(real_modules: dict[str, ModuleInfo]) -> None:
    source = """
from hassette.resources import mark_ready
from hassette.resources.base import Resource

class Ready(Resource):
    async def on_initialize(self) -> None:
        self.finish()

    def finish(self) -> None:
        mark_ready(self, reason="done")
"""
    assert check_synthetic(real_modules, source) == []


def test_accepts_mark_ready_inherited_from_scanned_base(real_modules: dict[str, ModuleInfo]) -> None:
    source = """
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready

class Base(Resource):
    async def on_initialize(self) -> None:
        mark_ready(self, reason="done")

class Child(Base):
    pass
"""
    assert check_synthetic(real_modules, source) == []


def test_ignore_marker_exempts_class(real_modules: dict[str, ModuleInfo]) -> None:
    source = f"""
from hassette.resources.base import Resource

class Exempt(Resource):  {IGNORE_MARKER}
    pass
"""
    assert check_synthetic(real_modules, source) == []


def test_unrelated_mark_ready_name_does_not_count(real_modules: dict[str, ModuleInfo]) -> None:
    source = """
from hassette.resources.base import Resource

def mark_ready(resource, reason=None):
    pass

class Impostor(Resource):
    async def on_initialize(self) -> None:
        mark_ready(self, reason="not the framework function")
"""
    assert check_synthetic(real_modules, source) == ["hassette.synthetic_resource.Impostor (synthetic_resource.py:7)"]
