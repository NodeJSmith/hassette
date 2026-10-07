#!/usr/bin/env -S uv run
"""Lint guard: keep ``state_manager.pyi``'s typed domain properties in sync with the state models.

``StateManager`` serves ``self.states.<domain>`` dynamically through ``__getattr__``, so the only
static typing for those accessors is the hand-written ``state_manager.pyi`` stub. Nothing else
ties the stub to the models: a new state class with its own ``domain: Literal["..."]`` works at
runtime but is invisible to IDEs and pyright until someone remembers to add a stub property.

The expected set of stub properties is built from two sources:

    1. The runtime state catalog (``hassette.models.states.catalog``) that ``__getattr__`` resolves
       against — each registered domain, typed as its state class. Importing the package runs the
       same ``BaseState`` registration the framework does, so no registration rule is re-derived here.
    2. Every ``@property`` defined explicitly on ``StateManager`` in ``state_manager.py`` (read via
       AST) whose return annotation is ``DomainStates[...]`` (the narrowed sensor-shape accessors).

The actual set is every ``@property`` on ``StateManager`` in the stub returning
``DomainStates[...]``. A property missing from either side, or typed with a different state class,
is reported.

Usage:
    uv run python tools/check_state_manager_stub.py
"""

import ast
import sys
from collections.abc import Mapping
from pathlib import Path

from lint_helpers import REPO_ROOT, run_check

from hassette.models.states import catalog

STATE_MANAGER_DIR = REPO_ROOT / "src" / "hassette" / "state_manager"
STUB_PATH = STATE_MANAGER_DIR / "state_manager.pyi"
SOURCE_PATH = STATE_MANAGER_DIR / "state_manager.py"

CLASS_NAME = "StateManager"
CONTAINER_NAME = "DomainStates"


def catalog_domains() -> dict[str, str]:
    """Return ``{domain: state class name}`` from the runtime catalog ``StateManager.__getattr__`` resolves against."""
    return {str(key.domain): cls.__name__ for key, cls in catalog.snapshot_catalog().items()}


def dotted_tail(node: ast.expr) -> str | None:
    """Return ``X`` for a bare ``X`` or qualified ``a.b.X`` name reference, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def domain_state_properties(path: Path) -> tuple[int, dict[str, tuple[int, str]]]:
    """Return ``StateManager``'s line and ``{name: (lineno, state class)}`` for its ``DomainStates[...]`` properties.

    The class line anchors "missing property" violations, which have no property line of their own;
    only the stub caller needs it.

    Handles both a bare annotation (the stub) and a string annotation (``state_manager.py`` quotes
    its forward references). The state class is the last dotted component, so ``states.LightState``
    and ``LightState`` compare equal.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    cls = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME),
        None,
    )
    if cls is None:
        raise SystemExit(f"ERROR: class {CLASS_NAME} not found in {path}")

    found: dict[str, tuple[int, str]] = {}
    for stmt in cls.body:
        if not isinstance(stmt, ast.FunctionDef) or stmt.returns is None:
            continue
        if not any(isinstance(dec, ast.Name) and dec.id == "property" for dec in stmt.decorator_list):
            continue
        state_class = container_arg(stmt.returns)
        if state_class is not None:
            found[stmt.name] = (stmt.lineno, state_class)
    return cls.lineno, found


def container_arg(returns: ast.expr) -> str | None:
    """Return ``X`` from a ``DomainStates[<...>.X]`` annotation (optionally string-quoted), else None."""
    if isinstance(returns, ast.Constant) and isinstance(returns.value, str):
        returns = ast.parse(returns.value, mode="eval").body
    if not (isinstance(returns, ast.Subscript) and isinstance(returns.value, ast.Name)):
        return None
    if returns.value.id != CONTAINER_NAME:
        return None
    # Anything but a single class reference (e.g. a union) keeps its full source text, so it can
    # never compare equal to an expected class name and surfaces as a mismatch.
    return dotted_tail(returns.slice) or ast.unparse(returns.slice)


def check_stub(
    stub_path: Path, model_props: Mapping[str, str] | None = None, source_path: Path = SOURCE_PATH
) -> list[tuple[int, str]]:
    """Compare the stub's typed domain properties against the catalog and explicit source properties.

    ``model_props`` maps domain to state class name; it defaults to the runtime catalog.
    """
    if model_props is None:
        model_props = catalog_domains()
    _, source_props = domain_state_properties(source_path)
    for name, (lineno, state_class) in source_props.items():
        if name in model_props and model_props[name] != state_class:
            raise SystemExit(
                f"ERROR: {source_path}:{lineno} property `{name}` typed {state_class}, "
                f"but the `{name}` state model is {model_props[name]}"
            )
    expected = {**model_props, **{name: state_class for name, (_, state_class) in source_props.items()}}
    class_lineno, actual = domain_state_properties(stub_path)

    violations = [
        (class_lineno, f"missing property `{name}` -> {CONTAINER_NAME}[states.{expected[name]}]")
        for name in sorted(expected.keys() - actual.keys())
    ]
    for name in sorted(actual.keys() - expected.keys()):
        lineno, state_class = actual[name]
        violations.append((lineno, f"property `{name}` ({state_class}) has no matching state model domain"))
    for name in sorted(expected.keys() & actual.keys()):
        lineno, state_class = actual[name]
        if state_class != expected[name]:
            violations.append((lineno, f"property `{name}` typed {state_class}, expected {expected[name]}"))
    return violations


def main() -> int:
    return run_check(
        [STUB_PATH],
        REPO_ROOT,
        check_stub,
        summary="state_manager.pyi drift(s) from the state models",
        ok="state_manager.pyi domain properties match the state models.",
        footer=(
            "Add, remove, or retype the `@property` entries on StateManager in\n"
            "src/hassette/state_manager/state_manager.pyi so each state model domain has one."
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
