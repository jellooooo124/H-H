"""Deprecated import path; canonical persistence adapter lives in infrastructure.persistence."""
from .infrastructure.persistence.sql_store import Store

__all__ = ["Store"]
