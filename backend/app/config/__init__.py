"""Application configuration package.

Exposes the singleton :data:`app.config.settings.settings` instance that
centralizes all environment-driven configuration for the backend.
"""

from app.config.settings import Settings, settings

__all__ = ["Settings", "settings"]
