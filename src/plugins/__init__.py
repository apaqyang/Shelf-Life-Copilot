"""Enterprise plugin seam — Open Core registration boundary.

Open-source core ships with no enterprise plugins. See `loader.load_plugins`.
"""

from src.plugins.loader import DEFAULT_PLUGINS_ROOT, load_plugins
from src.plugins.registry import PluginRegistry

__all__ = ["DEFAULT_PLUGINS_ROOT", "PluginRegistry", "load_plugins"]
