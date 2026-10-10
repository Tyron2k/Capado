"""Guard calendar defaults and inclusive dated profile bindings.

Revision ID: 004
Revises: 003
"""

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Report inconsistent legacy rows before changing schema or installing guards."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE resource_work_profiles, sites, work_week_profiles IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    problems = []
    for table in ("sites", "work_week_profiles"):
        ids = list(
            connection.scalars(
                sa.text(f"SELECT id FROM {table} WHERE is_default ORDER BY id")
            )
        )
        if len(ids) > 1:
            problems.append(f"{table} multiple defaults: " + ", ".join(map(str, ids)))
    inactive = list(
        connection.scalars(
            sa.text(
                "SELECT id FROM sites WHERE is_default AND NOT is_active ORDER BY id"
            )
        )
    )
    if inactive:
        problems.append("inactive default sites: " + ", ".join(map(str, inactive)))
    invalid = list(
        connection.scalars(
            sa.text(
                "SELECT id FROM resource_work_profiles WHERE (resource_id IS NULL) = (group_id IS NULL) "
                "OR valid_until < valid_from ORDER BY id"
            )
        )
    )
    if invalid:
        problems.append(
            "invalid work-profile target/period: " + ", ".join(map(str, invalid))
        )
    else:
        overlaps = connection.execute(
            sa.text(
                "SELECT a.id, b.id FROM resource_work_profiles a JOIN resource_work_profiles b ON a.id < b.id "
                "AND (a.resource_id=b.resource_id OR a.group_id=b.group_id) "
                "AND daterange(a.valid_from, a.valid_until, '[]') && daterange(b.valid_from, b.valid_until, '[]') "
                "ORDER BY a.id,b.id"
            )
        ).all()
        if overlaps:
            problems.append(
                "overlapping work-profile bindings: "
                + "; ".join(f"{a}, {b}" for a, b in overlaps)
            )
    if problems:
        raise RuntimeError(
            "Calendar integrity conflicts prevent migration 004. Review these IDs on a restored backup "
            "and resolve them explicitly before retrying; no data were deleted: "
            + "; ".join(problems)
        )
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    for table in ("sites", "work_week_profiles"):
        op.create_index(
            f"uq_{table}_default",
            table,
            ["is_default"],
            unique=True,
            postgresql_where=sa.text("is_default"),
        )
    op.create_check_constraint(
        "ck_sites_default_active", "sites", "NOT is_default OR is_active"
    )
    for target in ("resource", "group"):
        op.execute(
            sa.text(
                f"ALTER TABLE resource_work_profiles ADD CONSTRAINT ex_work_profiles_{target}_period "
                f"EXCLUDE USING gist ({target}_id WITH =, daterange(valid_from, valid_until, '[]') WITH &&) "
                f"WHERE ({target}_id IS NOT NULL)"
            )
        )


def downgrade() -> None:
    """Remove guards without deleting calendars or a possibly shared extension."""
    for target in ("group", "resource"):
        op.drop_constraint(
            f"ex_work_profiles_{target}_period",
            "resource_work_profiles",
        )
    op.drop_constraint("ck_sites_default_active", "sites", type_="check")
    for table in ("work_week_profiles", "sites"):
        op.drop_index(f"uq_{table}_default", table_name=table)
