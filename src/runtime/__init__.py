"""Long-running service runtime: Settings + lifespan + entry points.

`src/main.py` reads from here. The CLI / tools layer keeps its own argparse
because they're one-shot — only the long-running uvicorn process picks up
environment-driven configuration.
"""

from src.runtime.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
