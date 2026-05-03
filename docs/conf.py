import sys
from pathlib import Path

# Rend le package importable sans installation
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

# ---------------------------------------------------------------------------
# Informations projet
# ---------------------------------------------------------------------------
project   = "test_multi_process_pandas"
copyright = "2026, Lolo"
author    = "Lolo"
release   = "2026.0.1"

# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",        # génération depuis docstrings
    "sphinx.ext.napoleon",       # support Google/NumPy docstrings
    "sphinx.ext.viewcode",       # lien [source] vers le code
    "sphinx.ext.intersphinx",    # références croisées vers docs externes
    "sphinx.ext.autosectionlabel",  # :ref: automatique sur toutes les sections
]

# Évite les conflits de labels entre fichiers
autosectionlabel_prefix_document = True

# ---------------------------------------------------------------------------
# Napoleon (style de docstrings)
# ---------------------------------------------------------------------------
napoleon_google_docstring  = True
napoleon_numpy_docstring   = False
napoleon_use_param         = True
napoleon_use_returns       = True
napoleon_use_rtype         = False

# ---------------------------------------------------------------------------
# Autodoc
# ---------------------------------------------------------------------------
autodoc_default_options = {
    "members":          True,
    "undoc-members":    False,
    "private-members":  False,
    "show-inheritance": True,
    "member-order":     "bysource",
}
autodoc_typehints          = "description"
autodoc_typehints_format   = "short"

# ---------------------------------------------------------------------------
# Intersphinx — références vers docs externes
# ---------------------------------------------------------------------------
intersphinx_mapping = {
    "python":  ("https://docs.python.org/3", None),
    "numpy":   ("https://numpy.org/doc/stable", None),
    "pandas":  ("https://pandas.pydata.org/docs", None),
}

# ---------------------------------------------------------------------------
# Chemins et patterns
# ---------------------------------------------------------------------------
templates_path   = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# ---------------------------------------------------------------------------
# Thème HTML
# ---------------------------------------------------------------------------
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth":    4,
    "collapse_navigation": False,
    "sticky_navigation":   True,
    "titles_only":         False,
}
html_static_path = ["_static"]
