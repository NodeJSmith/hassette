import sys
from pathlib import Path

# Ensure package imports work if needed
sys.path.insert(0, str((Path(__file__).parent.parent).resolve()))


project = "Hassette"
html_title = "Hassette"
copyright = "2025, Jessica Smith"
author = "Jessica Smith"

extensions = [
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",  # for Google/NumPy-style docstrings
    "sphinx.ext.intersphinx",  # for linking to external documentation
    "sphinxcontrib.autodoc_pydantic",  # renders BaseModel fields nicely
    "sphinx_copybutton",  # adds "copy" button to code blocks
    "autodoc2",
]

autodoc2_packages = [
    "../src/hassette",
]


# Intersphinx mapping for external library documentation
intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "aiohttp": ("https://docs.aiohttp.org/en/stable/", None),
    "whenever": ("https://whenever.readthedocs.io/en/latest/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

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
    "navigation_depth": 5,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "body_max_width": "100%",
}
html_css_files = ["style.css"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


autosummary_generate = True
autosummary_imported_members = True

autodoc2_class_docstring = "both"

typehints_fully_qualified = False  # makes types like `str` instead of `builtins.str`
typehints_use_signature = True

python_use_unqualified_type_names = True  # Sphinx ≥7


autodoc2_replace_annotations = [
    ("hassette.types.ChangeType", "hassette.types.types.ChangeType"),
    ("hassette.types.HandlerType", "hassette.types.types.HandlerType"),
    ("hassette.types.JobCallable", "hassette.types.types.JobCallable"),
    ("hassette.types.ScheduleStartType", "hassette.types.types.ScheduleStartType"),
    ("states.StateT", "hassette.models.states.base.StateT"),
]


autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_settings_show_config_summary = False
autodoc_pydantic_model_show_validator_summary = False
autodoc_pydantic_model_show_validator_members = False
autodoc_pydantic_settings_show_validator_summary = False
autodoc_pydantic_model_show_field_summary = False
autodoc_pydantic_settings_show_validator_members = False
autodoc_pydantic_settings_show_field_summary = False
autodoc_pydantic_model_show_json = False
autodoc_pydantic_field_list_validators = False
toc_object_entries_show_parents = "hide"  # Hide parent classes in the table of contents
