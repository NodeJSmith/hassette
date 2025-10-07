import sys
from pathlib import Path

# Ensure package imports work if needed
sys.path.insert(0, str((Path(__file__).parent.parent).resolve()))


project = "Hassette"
html_title = "Hassette"
copyright = "2025, Jessica Smith"
author = "Jessica Smith"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",  # for Google/NumPy-style docstrings
    "sphinxcontrib.autodoc_pydantic",  # renders BaseModel fields nicely
    "sphinx_copybutton",  # adds "copy" button to code blocks
]


myst_enable_extensions = ["fieldlist"]

PYDANTIC_IGNORE_FIELDS = [
    "dict",
    "copy",
    "parse_obj",
    "parse_raw",
    "parse_file",
    "schema",
    "schema_json",
    "model_validate",
    "model_validate_json",
    "model_validate_strings",
    "model_rebuild",
    "model_parametrized_name",
    "model_json_schema",
    "model_construct",
    "from_orm",
    "construct",
    "update_forward_refs",
    "validate",
    "json",
    "model_copy",
    "model_dump",
    "model_dump_json",
    "model_extra",
    "model_computed_fields",
    "model_fields",
    "model_fields_set",
    "model_config",
    "model_rebuild",
    "model_post_init",
]


master_doc = "index"
html_theme = "sphinx_rtd_theme"
templates_path = ["_templates"]
html_static_path = ["_static"]
html_theme_options = {
    "navigation_with_keys": True,
}
html_css_files = [
    "style.css",
]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


typehints_fully_qualified = False  # makes types like `str` instead of `builtins.str`

# Optional: only show class signatures (not constructor separately)
autodoc_class_signature = "separated"  # or "mixed"
# autodoc_inherit_docstrings = False

autodoc_default_flags = ["members"]
autosummary_generate = True
autosummary_imported_members = True
autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_validator_summary = False
autodoc_pydantic_model_show_validator_members = False
autodoc_pydantic_model_show_field_summary = False
autodoc_pydantic_model_show_json = False
toc_object_entries_show_parents = "hide"  # Hide parent classes in the table of contents
