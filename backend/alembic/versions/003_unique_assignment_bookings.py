"""Reject identical bookings without removing distinct resource/work-package intervals.

Revision ID: 003
Revises: 002
"""

import sqlalchemy as sa

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

BOOKINGS = {
    "personal": ("start_date", "end_date", "allocation_percent"),
    "infrastructure": ("start_at", "end_at"),
}


def upgrade() -> None:
    """Fail with row IDs on legacy duplicates; never guess which booking to retain."""
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE assignments IN SHARE ROW EXCLUSIVE MODE"))
    duplicates = []
    for kind, fields in BOOKINGS.items():
        columns = ", ".join(
            ("resource_type", "resource_id", "work_package_id", *fields)
        )
        rows = connection.execute(
            sa.text(
                f"SELECT array_agg(id ORDER BY id) AS ids FROM assignments "
                f"WHERE resource_type = '{kind}' GROUP BY {columns} HAVING count(*) > 1"
            )
        )
        duplicates.extend(str(r[0]) for r in rows)
    if duplicates:
        raise RuntimeError(
            "Identical assignment bookings prevent migration 003. "
            "Review these assignment IDs on a restored backup, resolve them explicitly, "
            "then retry; no rows were deleted: " + "; ".join(duplicates)
        )
    for kind, fields in BOOKINGS.items():
        op.create_index(
            f"uq_assignments_{kind}_booking",
            "assignments",
            ["resource_type", "resource_id", "work_package_id", *fields],
            unique=True,
            postgresql_where=sa.text(f"resource_type = '{kind}'"),
        )


def downgrade() -> None:
    """Remove the guards while preserving every booking."""
    for kind in reversed(BOOKINGS):
        op.drop_index(f"uq_assignments_{kind}_booking", table_name="assignments")
