"""add dpia screening runs

Revision ID: 1edcff27d5af
Revises: a1b2c3d4e5f6
Create Date: 2026-08-09 19:10:08.468382

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1edcff27d5af"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED_STATUSES = "'pending', 'running', 'ready_for_review', 'failed'"

_LIFECYCLE_CHECK = (
    "("
    "status = 'pending' "
    "AND evidence_snapshot IS NULL "
    "AND result IS NULL "
    "AND conclusion IS NULL "
    "AND model IS NULL "
    "AND prompt_version IS NULL "
    "AND error IS NULL"
    ") OR ("
    "status = 'running' "
    "AND result IS NULL "
    "AND conclusion IS NULL "
    "AND model IS NULL "
    "AND prompt_version IS NULL "
    "AND error IS NULL"
    ") OR ("
    "status = 'ready_for_review' "
    "AND evidence_snapshot IS NOT NULL "
    "AND result IS NOT NULL "
    "AND conclusion IS NOT NULL "
    "AND model IS NOT NULL "
    "AND prompt_version IS NOT NULL "
    "AND error IS NULL"
    ") OR ("
    "status = 'failed' "
    "AND result IS NULL "
    "AND conclusion IS NULL "
    "AND model IS NULL "
    "AND prompt_version IS NULL "
    "AND error IS NOT NULL "
    "AND btrim(error) <> ''"
    ")"
)


def upgrade() -> None:
    op.create_table(
        "screenings",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("conclusion", sa.String(32), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("rules_version", sa.String(64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_screenings_positive_version",
        ),
        sa.CheckConstraint(
            f"status IN ({_ALLOWED_STATUSES})",
            name="ck_screenings_status",
        ),
        sa.CheckConstraint(
            "btrim(rules_version) <> ''",
            name="ck_screenings_rules_version",
        ),
        sa.CheckConstraint(
            _LIFECYCLE_CHECK,
            name="ck_screenings_lifecycle",
        ),
        sa.UniqueConstraint(
            "project_id",
            "version",
            name="uq_screenings_project_version",
        ),
    )
    op.create_index(
        "ix_screenings_project_id",
        "screenings",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_screenings_project_id",
        table_name="screenings",
    )
    op.drop_table("screenings")
