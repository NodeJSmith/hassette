"""Sync facade generator package.

Re-exports the public API so existing imports (tests, CI) continue to work
via ``from hassette_codegen.sync_facade import ...``.
"""

from hassette_codegen.output import format_via_ruff as _format_via_ruff
from hassette_codegen.sync_facade.ast_utils import (
    BUILTIN_NAMES,
    INTERNAL_METHODS,
    LIFECYCLE_METHODS,
    STATE_CONVERSION_METHODS,
    STUB_MSG_GENERIC,
    STUB_MSG_STATE_CONVERSION,
    WELL_KNOWN_NAMES,
    _is_delegatable,
    _is_wrappable,
    _safe_parse,
    desync_docstring,
    format_signature_and_call,
    is_overload,
)
from hassette_codegen.sync_facade.cli import main
from hassette_codegen.sync_facade.generic import (
    BUS_CLASS_HEADER,
    BUS_HEADER,
    CLASS_HEADER,
    HEADER,
    SCHEDULER_CLASS_HEADER,
    SCHEDULER_HEADER,
    _generate_facade,
    gen_delegate,
    gen_wrapper,
    generate_sync,
    generate_sync_bus,
    generate_sync_scheduler,
)
from hassette_codegen.sync_facade.recording import generate_sync_recording
from hassette_codegen.sync_facade.recording_imports import (
    _build_precise_import_block,
    _collect_annotation_symbols,
    _collect_module_level_import_map,
    _collect_referenced_symbols,
    _collect_type_checking_import_map,
    _derive_recording_imports_strict,
)
from hassette_codegen.sync_facade.recording_transform import (
    _RecordingBodyRewriter,
    gen_recording_method,
    gen_recording_stub,
    is_not_implemented_only,
)

__all__ = [
    "BUILTIN_NAMES",
    "BUS_CLASS_HEADER",
    "BUS_HEADER",
    "CLASS_HEADER",
    "HEADER",
    "INTERNAL_METHODS",
    "LIFECYCLE_METHODS",
    "SCHEDULER_CLASS_HEADER",
    "SCHEDULER_HEADER",
    "STATE_CONVERSION_METHODS",
    "STUB_MSG_GENERIC",
    "STUB_MSG_STATE_CONVERSION",
    "WELL_KNOWN_NAMES",
    "_RecordingBodyRewriter",
    "_build_precise_import_block",
    "_collect_annotation_symbols",
    "_collect_module_level_import_map",
    "_collect_referenced_symbols",
    "_collect_type_checking_import_map",
    "_derive_recording_imports_strict",
    "_generate_facade",
    "_is_delegatable",
    "_is_wrappable",
    "_safe_parse",
    "desync_docstring",
    "format_signature_and_call",
    "gen_delegate",
    "gen_recording_method",
    "gen_recording_stub",
    "gen_wrapper",
    "generate_sync",
    "generate_sync_bus",
    "generate_sync_recording",
    "generate_sync_scheduler",
    "is_not_implemented_only",
    "is_overload",
    "_format_via_ruff",
    "main",
]
