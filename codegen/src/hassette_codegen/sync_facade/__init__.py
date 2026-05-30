"""Sync facade generator package.

Public API is re-exported here. Internal helpers (underscore-prefixed) are
importable directly from their submodules for testing.
"""

from hassette_codegen.sync_facade.ast_utils import (
    BUILTIN_NAMES,
    INTERNAL_METHODS,
    LIFECYCLE_METHODS,
    STATE_CONVERSION_METHODS,
    STUB_MSG_GENERIC,
    STUB_MSG_STATE_CONVERSION,
    WELL_KNOWN_NAMES,
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
    gen_delegate,
    gen_wrapper,
    generate_sync,
    generate_sync_bus,
    generate_sync_scheduler,
)
from hassette_codegen.sync_facade.recording import generate_sync_recording
from hassette_codegen.sync_facade.recording_transform import (
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
    "main",
]
