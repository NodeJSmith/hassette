import os
import sys
from pathlib import Path

# Project root → ensure AutoAPI can find files
ROOT = Path(__file__).parent.parent.absolute()
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

project = "Hassette"
extensions = [
    "sphinx.ext.napoleon",  # Google/NumPy docstrings -> nice HTML
    "sphinx.ext.intersphinx",
    "autoapi.extension",
    "hassette.sphinx",  # custom Sphinx helpers
    "sphinx_copybutton",  # "copy" button for code blocks
    "sphinx.ext.viewcode",  # add links to source code
    "sphinxcontrib.mermaid",  # mermaid diagrams
]

html_theme = "sphinx_rtd_theme"
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "_autoapi_templates", "sphinx.py"]


# --- AutoAPI: parse Python source (no runtime import) ---
autoapi_type = "python"
autoapi_dirs = [os.path.join(SRC, "hassette")]
autoapi_add_toctree_entry = True
autoapi_member_order = "bysource"
autoapi_keep_files = True
autoapi_root = "code-reference"  # where in the ToC it lands
autoapi_python_class_content = "both"  # class docstring + __init__ docstring
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
]
autoapi_template_dir = "_autoapi_templates"
# optional: hide private/dunder unless you need them
autoapi_python_use_implicit_namespaces = True
autoapi_own_page_level = "function"  # one page per object (nice deep linking)

# --- Google docstrings tuning ---
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = True

# --- Types & cross-refs ---
# AutoAPI reads annotations from source; add intersphinx so externals link
intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "aiohttp": ("https://docs.aiohttp.org/en/stable/", None),
    "whenever": ("https://whenever.readthedocs.io/en/latest/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}


python_use_unqualified_type_names = True

# --- Make nitpicky helpful, not hateful (optional) ---
nitpicky = True
nitpick_ignore_regex = [
    # Don't nag about std typing internals you don't want to document
    (r"py:.*", r"^typing(_extensions)?\."),
    (r"py:.*", r"^builtins\."),
]

html_static_path = ["_static"]  # <— ensure docs/_static/ exists
html_css_files = ["style.css"]  # <— ensure docs/_static/style.css exists
