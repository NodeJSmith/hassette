"""HA core source resolution, startup checks, and domain discovery."""

import ast
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from hassette_codegen.extractors._common import find_entity_class


@dataclass
class DiscoveredDomain:
    name: str
    path: Path
    has_services_yaml: bool
    has_const_py: bool


@dataclass
class HASource:
    path: Path
    version: str
    _cleanup_dir: Path | None = field(default=None, repr=False)

    def cleanup(self) -> None:
        if self._cleanup_dir is not None:
            import shutil

            shutil.rmtree(self._cleanup_dir, ignore_errors=True)


def resolve_source(*, ha_core_path: Path | None = None, ha_release_tag: str | None = None) -> HASource:
    """Resolve HA core source from local path or by cloning a release tag."""
    if ha_core_path is not None:
        components = ha_core_path / "homeassistant" / "components"
        if not components.is_dir():
            raise SystemExit(f"Invalid HA core path: {ha_core_path} (missing homeassistant/components/)")
        version = _detect_version(ha_core_path)
        _warn_version_mismatch(version)
        return HASource(path=ha_core_path, version=version)

    if ha_release_tag is not None:
        clone_dir = Path(tempfile.mkdtemp(prefix="hassette-codegen-ha-"))
        url = "https://github.com/home-assistant/core.git"
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", ha_release_tag, url, str(clone_dir)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise SystemExit(f"Cloning {url} at tag {ha_release_tag} timed out after 120s") from exc
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"Failed to clone {url} at tag {ha_release_tag}: {exc.stderr.strip()}") from exc
        return HASource(path=clone_dir, version=ha_release_tag, _cleanup_dir=clone_dir)

    raise SystemExit("Must specify either --ha-core-path or --ha-release-tag")


def _warn_version_mismatch(detected_version: str) -> None:
    """Warn if the local HA checkout doesn't match the pinned version."""
    version_file = Path(__file__).resolve().parent.parent.parent / "ha-version.txt"
    if not version_file.exists():
        return
    pinned = version_file.read_text(encoding="utf-8").strip()
    if pinned and pinned not in detected_version:
        print(
            f"WARNING: Local HA core version ({detected_version}) does not match "
            f"pinned version ({pinned}). Generated output may differ from CI.",
            file=sys.stderr,
        )


def _detect_version(ha_core_path: Path) -> str:
    """Detect version from git describe or directory name."""
    try:
        result = subprocess.run(
            ["git", "-C", str(ha_core_path), "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ha_core_path.name


def check_python_version(ha_core_path: Path) -> None:
    """Verify the running Python meets HA core's REQUIRED_PYTHON_VER."""
    const_path = ha_core_path / "homeassistant" / "const.py"
    if not const_path.exists():
        raise SystemExit(f"Cannot find {const_path} to check REQUIRED_PYTHON_VER")

    required = _parse_required_python_ver(const_path)
    if required is None:
        raise SystemExit(f"Could not parse REQUIRED_PYTHON_VER from {const_path}")

    current = sys.version_info[:3]
    if current < required:
        req_str = ".".join(str(v) for v in required)
        cur_str = ".".join(str(v) for v in current)
        raise SystemExit(
            f"Generator requires Python {req_str}+ to parse HA core files (HA requires {req_str}, running {cur_str})"
        )


def _parse_required_python_ver(const_path: Path) -> tuple[int, int, int] | None:
    """Parse REQUIRED_PYTHON_VER tuple from HA's const.py via AST."""
    source = const_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(const_path))

    for node in ast.walk(tree):
        name: str | None = None
        value: ast.expr | None = None

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "REQUIRED_PYTHON_VER":
                    name = target.id
                    value = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "REQUIRED_PYTHON_VER":
                name = node.target.id
                value = node.value

        if name is not None and isinstance(value, ast.Tuple) and len(value.elts) == 3:
            parts = []
            for elt in value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, int):
                    parts.append(elt.value)
            if len(parts) == 3:
                return (parts[0], parts[1], parts[2])
    return None


def check_ruff_available() -> None:
    """Verify ruff is available on PATH."""
    try:
        subprocess.run(["ruff", "--version"], capture_output=True, timeout=10, check=True)
    except FileNotFoundError as exc:
        raise SystemExit("ruff not found on PATH. Install with: uv tool install ruff") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"ruff --version failed with exit code {exc.returncode}") from exc


def discover_domains(ha_core_path: Path) -> list[DiscoveredDomain]:
    """Discover core entity domains by scanning for CACHED_PROPERTIES_WITH_ATTR_."""
    components_dir = ha_core_path / "homeassistant" / "components"
    domains: list[DiscoveredDomain] = []

    for component_dir in sorted(components_dir.iterdir()):
        if not component_dir.is_dir():
            continue

        init_py = component_dir / "__init__.py"
        if not init_py.exists():
            continue

        source = init_py.read_text(encoding="utf-8")
        if "CACHED_PROPERTIES_WITH_ATTR_" not in source:
            continue

        try:
            tree = ast.parse(source, filename=str(init_py))
        except SyntaxError:
            continue
        if find_entity_class(tree) is None:
            continue

        domains.append(
            DiscoveredDomain(
                name=component_dir.name,
                path=component_dir,
                has_services_yaml=(component_dir / "services.yaml").exists(),
                has_const_py=(component_dir / "const.py").exists(),
            )
        )

    return domains
