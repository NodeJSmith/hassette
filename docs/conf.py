import sys
from pathlib import Path

project = "Hassette"
html_title = "Hassette"

# Ensure package imports work if needed
sys.path.insert(0, str((Path(__file__).parent.parent).resolve()))

extensions: list[str] = []
master_doc = "index"
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 2,
    "includehidden": True,
    "titles_only": False,
}
