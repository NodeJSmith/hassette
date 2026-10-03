"""Structural guards for web API errors.

- No module under `src/hassette/web/` other than `errors.py` constructs an `HTTPException` or
  builds a `{"detail": ...}` body by hand. Routes raise `WebApiError`; middleware calls
  `problem_response()`. Anything else would ship an error without the problem shape or a code.
- Every `ProblemCode` is documented in the error catalog page.
"""

import ast
from pathlib import Path

import pytest
from hassette_wire import ProblemCode

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = REPO_ROOT / "src" / "hassette" / "web"
ERRORS_MODULE = WEB_DIR / "errors.py"
CATALOG_PAGE = REPO_ROOT / "docs" / "pages" / "web-ui" / "api-errors.md"

HTTP_EXCEPTION_NAMES = frozenset(
    {"fastapi.HTTPException", "fastapi.exceptions.HTTPException", "starlette.exceptions.HTTPException"}
)


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Map each name bound by an import to the dotted name it refers to."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    root = alias.name.split(".")[0]
                    aliases[root] = root
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _dotted_name(expr: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(expr, ast.Name):
        return aliases.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        base = _dotted_name(expr.value, aliases)
        return None if base is None else f"{base}.{expr.attr}"
    return None


def _docstrings(tree: ast.AST) -> set[ast.AST]:
    """The docstring nodes in ``tree``: prose that may quote a body without building one."""
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, owners)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }


def find_bypasses(source: str) -> list[str]:
    """Return one description per hand-built error in ``source``."""
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    docstrings = _docstrings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted_name(node.func, aliases)
            if name in HTTP_EXCEPTION_NAMES:
                found.append(f"line {node.lineno}: constructs {name}")
            elif name == "dict" and any(keyword.arg == "detail" for keyword in node.keywords):
                found.append(f"line {node.lineno}: builds a detail body with dict()")
        elif isinstance(node, ast.Dict):
            if any(isinstance(key, ast.Constant) and key.value == "detail" for key in node.keys):
                found.append(f"line {node.lineno}: builds a detail body literal")
        elif isinstance(node, ast.Constant) and node not in docstrings:
            value = node.value
            if (isinstance(value, bytes) and b'"detail"' in value) or (isinstance(value, str) and '"detail"' in value):
                found.append(f"line {node.lineno}: builds a detail body as a string")
    return found


def scanned_modules() -> list[Path]:
    return sorted(path for path in WEB_DIR.rglob("*.py") if path != ERRORS_MODULE)


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi import HTTPException\nraise HTTPException(status_code=404)",
        "from fastapi import HTTPException as E\nraise E(404)",
        "from fastapi.exceptions import HTTPException\nHTTPException(404)",
        "from starlette.exceptions import HTTPException\nHTTPException(404)",
        "import fastapi\nfastapi.HTTPException(404)",
        "import fastapi as fa\nfa.HTTPException(404)",
        "import starlette.exceptions\nstarlette.exceptions.HTTPException(404)",
        "from starlette import exceptions\nexceptions.HTTPException(404)",
        'JSONResponse({"detail": "nope"}, status_code=401)',
        'JSONResponse(dict(detail="nope"), status_code=401)',
        'body = b\'{"detail":"nope"}\'',
        'Response(content=\'{"detail": "nope"}\', status_code=401)',
    ],
    ids=[
        "bare",
        "aliased",
        "fastapi-exceptions",
        "starlette",
        "module-attribute",
        "module-alias",
        "dotted-module",
        "submodule-import",
        "dict-literal",
        "dict-call",
        "raw-bytes",
        "raw-string",
    ],
)
def test_guard_catches_each_bypass_form(source: str) -> None:
    assert len(find_bypasses(source)) == 1


def test_guard_allows_the_mechanism() -> None:
    source = (
        "from hassette.web.errors import WebApiError, problem_response\n"
        "raise WebApiError(ProblemCode.APP_NOT_FOUND, 'gone')\n"
        "problem_response(ProblemCode.NOT_AUTHENTICATED, 'Not authenticated')\n"
        "details = {'detail_level': 1}\n"
        "def f():\n"
        '    """FastAPI answers 400 {"detail": "..."} here."""\n'
    )

    assert find_bypasses(source) == []


def test_scan_covers_the_error_producing_modules() -> None:
    scanned = {path.relative_to(WEB_DIR).as_posix() for path in scanned_modules()}

    assert {"app.py", "middleware.py", "body_limit.py", "routes/apps.py", "routes/logs.py"} <= scanned
    assert "errors.py" not in scanned


@pytest.mark.parametrize("module", scanned_modules(), ids=lambda path: path.relative_to(WEB_DIR).as_posix())
def test_web_modules_raise_errors_only_through_the_mechanism(module: Path) -> None:
    assert find_bypasses(module.read_text(encoding="utf-8")) == []


def test_every_problem_code_is_in_the_catalog() -> None:
    catalog = CATALOG_PAGE.read_text(encoding="utf-8")

    missing = [code.value for code in ProblemCode if f"`{code.value}`" not in catalog]

    assert missing == []
