"""Stable ASGI entrypoint; compatibility routes and new bounded modules stay separate."""
from .legacy_api import app, create_app

__all__ = ["app", "create_app"]
