import ast
import importlib
import pkgutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, get_args, get_origin

import hassette_wire
from hassette_wire.lenient import LenientValue

# Defined in a submodule but deliberately not exported (spec 121 D4): the Literals named only to back
# an Open<TypeName> alias, and lenient-parsing internals. The aliases themselves are recognized by
# their LenientValue marker.
NOT_EXPORTED_NAMES = {"BootIssueSeverity", "ExecutionKind", "HandlerKind", "LenientValue", "LOGGER"}


def is_exported_by_design(name: str, obj: object) -> bool:
    is_open_alias = get_origin(obj) is Annotated and any(isinstance(m, LenientValue) for m in get_args(obj)[1:])
    return name not in NOT_EXPORTED_NAMES and not is_open_alias


def test_package_imports() -> None:
    assert hassette_wire.__doc__


def test_import_loads_no_hassette_module() -> None:
    """Importing hassette_wire in a fresh interpreter must not pull in ``hassette``."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import hassette_wire; "
            "leaked = [m for m in sys.modules if m == 'hassette' or m.startswith('hassette.')]; "
            "assert not leaked, leaked",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _defined_names_in_module(module_file: Path) -> set[str]:
    """Top-level names actually defined (not merely imported) in a source file.

    Classes are found via ``ast.ClassDef``; simple aliases and constants via top-level
    ``Assign``/``AnnAssign`` with a bare ``Name`` target. Private names (leading underscore)
    are excluded.
    """
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_"):
                names.add(node.target.id)
    return names


def test_every_public_definition_is_exported_from_root() -> None:
    """Every class/alias/constant defined in a hassette_wire submodule is in __all__ and
    importable from the package root as the identical object.
    """
    package_dir = Path(hassette_wire.__file__).parent

    missing_from_all: list[str] = []
    identity_mismatches: list[str] = []
    all_defined: set[str] = set()

    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name == "__init__":
            continue
        module_file = package_dir / f"{module_info.name}.py"
        if not module_file.exists():
            continue

        submodule = importlib.import_module(f"hassette_wire.{module_info.name}")
        defined_names = _defined_names_in_module(module_file)
        all_defined |= defined_names

        for name in defined_names:
            if not is_exported_by_design(name, getattr(submodule, name)):
                assert name not in hassette_wire.__all__, f"{module_info.name}.{name} is exported but shouldn't be"
                continue
            if name not in hassette_wire.__all__:
                missing_from_all.append(f"{module_info.name}.{name}")
                continue

            submodule_obj = getattr(submodule, name)
            root_obj = getattr(hassette_wire, name)
            if root_obj is not submodule_obj:
                identity_mismatches.append(f"{module_info.name}.{name}")

    assert all_defined >= NOT_EXPORTED_NAMES, f"Stale exemptions: {NOT_EXPORTED_NAMES - all_defined}"
    assert not missing_from_all, f"Defined but not exported in __all__: {missing_from_all}"
    assert not identity_mismatches, f"Root export is not the same object: {identity_mismatches}"
