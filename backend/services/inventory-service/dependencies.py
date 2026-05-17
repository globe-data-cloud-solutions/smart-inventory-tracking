"""Inventory-service FastAPI dependencies.

get_current_user is a stub that returns None in local dev / unit tests.
In production it is replaced by the JWT-validated user injected by the
API gateway. Tests override it via app.dependency_overrides.
"""
from __future__ import annotations


def get_current_user():  # pragma: no cover
    """Placeholder — overridden by API gateway middleware in production."""
    return None
