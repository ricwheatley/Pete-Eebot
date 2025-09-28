# (Functional) Initializes config package (imports Settings instance)

from .config import Settings, get_env, settings

__all__ = ["Settings", "settings", "get_env"]

