"""Native typed mappings share metadata with the remaining SQLModel entities."""

from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
from sqlmodel import SQLModel


class ORMModel(MappedAsDataclass, DeclarativeBase, kw_only=True, eq=False):
    """Keep eager constructor defaults and one Alembic schema."""

    metadata = SQLModel.metadata
