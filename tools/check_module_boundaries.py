#!/usr/bin/env python3
"""CI guard: enforce architectural import boundaries between hassette subpackages.

Hassette has layered subpackages (``types``, ``models``, ``config``, ``api``,
``bus``, ``core``, ``app``, ``web``, ``test_utils``, …). Nothing in the type
checker or test suite stops a lower layer from importing a higher one, so
boundary erosion compiles and passes silently. This guard fails such imports.

Detection is AST-based and considers runtime imports only — anything inside an
``if TYPE_CHECKING:`` block is exempt, since type-only imports do not create a
runtime dependency.

Import boundaries enforced today (``RULES``):
- ``test_utils`` isolation — production code must not import test helpers.
- ``api → core`` — api is a service layer and must not import core at runtime.
- ``utils → events`` — utils sits below events; ``is_event_type`` has moved to events/.
- ``web → core`` — web-facing data types live in hassette.schemas, not core.
- ``bus → core`` — bus is a service layer and must not import core at runtime (#1089).

The full layer DAG is NOT enforced here yet. The remaining runtime cycles —
``scheduler``↔``core`` (``SchedulerService``),
``state_manager``↔``core`` (``StateProxy``) — import real core logic, not data, so
breaking them needs a relocate-vs-protocol-inversion decision deferred to an ADR
(#1079 tracks breaking these cycles; #633 tracks full DAG enforcement).
``RULES`` is a list so each boundary is added as it becomes clean.

Import rules are structural violations, not style — there is no escape hatch. A
production module that needs a test helper signals a misplaced helper, not a
boundary to annotate.

This guard also forbids **private-attribute reach-through** into the Hassette core
object — ``hassette._foo`` / ``self.hassette._foo`` — anywhere outside ``core/``
and the ``test_utils/`` test harness (#1091). Subsystems should read public
properties, not private slots: the audit found the reach-throughs guarded null
state divergently and that ``python -O`` strips their ``assert`` guards. Unlike
the import rules, the private-attr rule has an escape hatch — ``PRIVATE_ATTR_ALLOWLIST``
— because a few framework internals (a hot-path loop-thread check, a test-harness
bypass hook) legitimately read private state. Each allowlist entry is a conscious,
auditable exception with a reason; entries tagged ``TODO`` are removed when the
public-property fix lands.

Usage:
    python tools/check_module_boundaries.py
"""

import ast
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lint_helpers import iter_py_files, run_check

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "hassette"


@dataclass(frozen=True)
class Rule:
    """A forbidden-import boundary.

    ``applies`` decides whether the rule governs a source file's layer; ``forbids``
    decides whether an imported ``hassette.*`` module name violates it.
    """

    name: str
    applies: Callable[[str], bool]
    forbids: Callable[[str], bool]
    reason: str


RULES: list[Rule] = [
    Rule(
        name="test_utils-isolation",
        applies=lambda layer: layer != "test_utils",
        forbids=lambda module: module == "hassette.test_utils" or module.startswith("hassette.test_utils."),
        reason="production code must not import test helpers from hassette.test_utils",
    ),
    Rule(
        name="api-no-core",
        applies=lambda layer: layer == "api",
        forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
        reason="api must not import core at runtime; core sits above the service layer (#1079)",
    ),
    Rule(
        name="utils-no-events",
        applies=lambda layer: layer == "utils",
        forbids=lambda module: module == "hassette.events" or module.startswith("hassette.events."),
        reason="utils sits below events; the only upward dependency (is_event_type) has moved to events/",
    ),
    Rule(
        name="web-no-core",
        applies=lambda layer: layer == "web",
        forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
        reason="web must not runtime-import core; web-facing data types live in hassette.schemas",
    ),
    Rule(
        name="bus-no-core",
        applies=lambda layer: layer == "bus",
        forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
        reason="bus must not import core at runtime; core sits above the service layer (#1089)",
    ),
]


#: Layers that own or legitimately wire Hassette internals, so reading ``hassette._foo``
#: there is not a reach-through. ``core`` is where ``Hassette`` lives; ``test_utils`` is the
#: test harness, whose whole job is assembling real components from their private slots.
PRIVATE_ATTR_EXEMPT_LAYERS = frozenset({"core", "test_utils"})

#: Reason shown for a private-attr reach-through violation.
PRIVATE_ATTR_REASON = (
    "subsystem code must not read private attributes of the Hassette core object; "
    "use a public property (or add a reasoned PRIVATE_ATTR_ALLOWLIST entry for genuine internals)"
)

#: (src-relative POSIX path, private attr name) pairs allowed to reach into ``hassette._foo``.
#: Each is a conscious exception. ``TODO`` entries are removed once the corresponding
#: public-property fix lands (the audit's N1 — service slots that should expose guarded
#: properties), at which point the rule enforces the boundary on those sites.
PRIVATE_ATTR_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        # Hot-path loop-thread identity check — framework fast path, intentionally direct.
        ("task_bucket/task_bucket.py", "_loop_thread_id"),
        # Test-harness dependency-check bypass — internal coordination hook between Resource and Hassette.
        ("resources/base.py", "_should_skip_dependency_check"),
        # TODO(#1091-followup): route through a guarded public property when the service-slot
        # public-property fix (audit N1) lands; remove these two entries then.
        ("scheduler/scheduler.py", "_scheduler_service"),
        ("bus/bus.py", "_bus_service"),
    }
)


def layer_of(path: Path) -> str:
    """Return the top-level subpackage name a source file belongs to."""
    rel = path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else "<root>"


def package_of(path: Path) -> str:
    """Return the dotted package a file's relative imports resolve against.

    ``src/hassette/app/utils.py`` and ``src/hassette/app/__init__.py`` both anchor
    at ``hassette.app`` — the package is every path part except the file stem.
    """
    rel = path.relative_to(SRC.parent).with_suffix("")  # e.g. hassette/app/utils
    return ".".join(rel.parts[:-1])


def type_checking_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Return line spans of the statements inside ``if TYPE_CHECKING:`` blocks.

    Imports within these spans are exempt. Only the ``if`` body is collected — an
    ``else`` branch runs at runtime, so spanning the whole ``if`` node (which would
    cover the ``else``) would wrongly exempt runtime imports there.
    """
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_tc = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if is_tc:
            ranges.extend((stmt.lineno, stmt.end_lineno or stmt.lineno) for stmt in node.body)
    return ranges


def resolved_from_module(node: ast.ImportFrom, package: str | None) -> str | None:
    """Resolve the ``from`` target of an ``ImportFrom`` to an absolute dotted module.

    Absolute imports return ``node.module`` unchanged. Relative imports are resolved
    against ``package`` (``from ..test_utils import x`` inside ``hassette.core`` →
    ``hassette.test_utils``). Returns None when there is no package to anchor a
    relative import or the level climbs above the root.
    """
    if node.level == 0:
        return node.module
    if package is None:
        return None
    base = package.split(".")
    drop = node.level - 1
    if drop >= len(base):
        return None  # climbs to or above the root package — Python rejects this too
    anchor = base[: len(base) - drop] if drop else base
    return ".".join([*anchor, *(node.module.split(".") if node.module else [])])


def runtime_imports(tree: ast.AST, package: str | None = None) -> list[tuple[int, str]]:
    """Return (lineno, imported hassette.* module) for every runtime import.

    ``package`` is the importing module's dotted package, used to resolve relative
    imports; when omitted, relative imports are skipped.
    """
    tc_ranges = type_checking_ranges(tree)

    def in_type_checking(lineno: int) -> bool:
        return any(start <= lineno <= end for start, end in tc_ranges)

    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not in_type_checking(node.lineno):
            module = resolved_from_module(node, package)
            if module == "hassette":
                # Bare ``hassette`` target (``from hassette import test_utils`` or the
                # relative ``from .. import test_utils``): the alias names are the
                # submodules, so reassemble ``hassette.<name>`` per alias.
                out.extend((node.lineno, f"hassette.{alias.name}") for alias in node.names if alias.name != "*")
            elif module and module.startswith("hassette."):
                out.append((node.lineno, module))
        elif isinstance(node, ast.Import) and not in_type_checking(node.lineno):
            out.extend((node.lineno, alias.name) for alias in node.names if alias.name.startswith("hassette."))
    return out


def is_private_attr(name: str) -> bool:
    """True for a single-underscore private name (``_foo``), not a dunder or mangled name.

    ``_loop_thread_id`` matches; ``__init__`` and ``__slots`` do not. The reach-through the
    audit documents is single-underscore private slots, not name-mangled or dunder members.
    """
    return name.startswith("_") and not name.startswith("__")


def value_is_hassette(value: ast.expr) -> bool:
    """True when an attribute's value refers to the Hassette core object.

    Matches the bare name ``hassette`` and any attribute access ending in ``.hassette``
    (``self.hassette``, ``app.hassette``) — the documented ``hassette._foo`` reach-through.
    Own-private access such as ``self._foo`` does not match, so it is never flagged.
    """
    if isinstance(value, ast.Name):
        return value.id == "hassette"
    return isinstance(value, ast.Attribute) and value.attr == "hassette"


def private_hassette_accesses(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, attr) for every ``hassette._private`` attribute access in the tree."""
    return [
        (node.lineno, node.attr)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and is_private_attr(node.attr) and value_is_hassette(node.value)
    ]


def is_allowlisted(rel_path: str | None, attr: str) -> bool:
    """True when reaching ``hassette.{attr}`` from ``rel_path`` is an explicit allowlist entry.

    A missing ``rel_path`` is never allowlisted, so detection-only callers (which pass no path)
    see every access flagged — flagging is the safe default, and ``check_file`` always supplies
    the path in real runs.
    """
    return rel_path is not None and (rel_path, attr) in PRIVATE_ATTR_ALLOWLIST


def check_source(
    source: str, layer: str, package: str | None = None, rel_path: str | None = None
) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) for boundary violations in a source string.

    ``package`` anchors relative imports; pass it to check the relative-import forms.
    ``rel_path`` is the src-relative POSIX path used to consult ``PRIVATE_ATTR_ALLOWLIST``;
    when omitted, no allowlist entry applies (every private-attr access in scope is flagged).
    """
    tree = ast.parse(source)
    violations = [
        (lineno, f"{rule.name}: imports {module} — {rule.reason}")
        for lineno, module in runtime_imports(tree, package)
        for rule in RULES
        if rule.applies(layer) and rule.forbids(module)
    ]
    if layer not in PRIVATE_ATTR_EXEMPT_LAYERS:
        violations.extend(
            (lineno, f"private-attr-reach-through: accesses hassette.{attr} — {PRIVATE_ATTR_REASON}")
            for lineno, attr in private_hassette_accesses(tree)
            if not is_allowlisted(rel_path, attr)
        )
    return sorted(violations)


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) for every boundary violation in the file.

    Always passes the file's src-relative path, so ``PRIVATE_ATTR_ALLOWLIST`` is consulted.
    """
    return check_source(path.read_text(), layer_of(path), package_of(path), rel_path=path.relative_to(SRC).as_posix())


def iter_paths() -> list[Path]:
    """Return every .py file under src/hassette, sorted for stable output."""
    return iter_py_files(REPO_ROOT, ["src/hassette"])


def main() -> int:
    return run_check(
        iter_paths(),
        REPO_ROOT,
        check_file,
        summary="module-boundary violation(s)",
        ok=f"no module-boundary violations across {len(RULES)} import rule(s) + the private-attr rule.",
    )


if __name__ == "__main__":
    sys.exit(main())
