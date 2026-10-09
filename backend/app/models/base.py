"""Shared native SQLAlchemy metadata and eager, identity-based ORM constructors."""

from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


class ORMModel(MappedAsDataclass, DeclarativeBase, kw_only=True, eq=False):
    """One mapper registry and metadata for persistence and Alembic."""


def column_values(obj: ORMModel) -> dict[str, Any]:
    """Read persisted scalar attributes, excluding relationships and ORM state."""
    return {
        attr.key: getattr(obj, attr.key) for attr in inspect(type(obj)).column_attrs
    }
