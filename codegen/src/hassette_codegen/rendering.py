"""Render upstream-derived values into generated Python source.

Every string codegen pulls out of the Home Assistant checkout — service names, enum member
values, sensor constants, docstring prose — is eventually interpolated into generated source.
Doing that with an f-string or a bare Jinja placeholder lets a quote character change the
*structure* of the output rather than its content, and `ruff` plus `py_compile` only validate
that the result is still syntactically valid Python. An input that stays valid while meaning
something else passes every existing gate.

These helpers are the one place that turns an upstream value into source text. Use them instead
of hand-quoting; ``py_literal`` is also registered as a Jinja filter for the templates.
"""

import json
import keyword


class UnsafeGeneratedValueError(ValueError):
    """An upstream-derived value cannot be safely rendered into generated source."""


def py_literal(value: object) -> str:
    """Render ``value`` as a Python literal.

    Strings go through ``json.dumps``, following the ``tojson`` filter already used for the
    datetime field validator in ``state_model.py.j2``: JSON string syntax is a subset of Python's,
    it escapes quotes and backslashes, and it always emits double quotes — which is what
    ``ruff format`` settles on anyway, so unformatted output stays readable and diff-free.
    ``ensure_ascii=False`` keeps non-ASCII characters intact rather than expanding them to escapes.

    ``int`` (and therefore ``bool``) is the only other type codegen emits. Anything else would
    render as an unparseable ``<object at 0x...>``, so refuse it rather than emit broken source.
    """
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return repr(value)
    raise UnsafeGeneratedValueError(f"cannot render {type(value).__name__} as a Python literal: {value!r}")


def escape_docstring_text(text: str) -> str:
    """Neutralize characters that would break out of a triple-quoted docstring.

    ``build_method_docstring`` assembles docstring lines that a template inserts as raw source,
    so the text has to be safe before it is wrapped. A ``\"\"\"`` in the text would close the
    docstring and put the remainder in executable position; a trailing backslash would escape
    the closing delimiter; a NUL is the one character Python refuses to read in source at all,
    which would leave the whole module uncompilable.

    Order matters twice over: backslashes are doubled first so the ones this function introduces
    are not doubled in turn, and the NUL escape is written last for the same reason.

    Whitespace is deliberately untouched. Callers collapse runs of whitespace before wrapping,
    so an embedded newline is already a space by the time it reaches the docstring. (Python
    normalizes a lone carriage return in source to a newline, so the text is not preserved
    byte-for-byte, but nothing structural depends on it.)

    One precondition stays with the caller: a single trailing quote is left alone, so the closing
    delimiter must not sit directly against the text or it would read as a fourth quote.
    ``build_method_docstring`` puts it on its own line.
    """
    return text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"').replace("\x00", "\\x00")


def require_identifier(value: str, *, kind: str) -> str:
    """Return ``value`` if it is usable as a Python identifier, else raise.

    Identifier positions — method names, parameter names, module paths — accept no escaping, so
    the only safe handling is to reject the value and skip whatever depends on it. Keywords pass
    ``str.isidentifier()`` but are not usable as names, hence the second check.
    """
    if not value.isidentifier() or keyword.iskeyword(value):
        raise UnsafeGeneratedValueError(f"{kind} {value!r} is not a usable Python identifier")
    return value
