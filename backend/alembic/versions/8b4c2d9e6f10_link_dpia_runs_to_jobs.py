"""link dpia runs to jobs

Revision ID: 8b4c2d9e6f10
Revises: 1edcff27d5af
Create Date: 2026-08-11 12:36:43.331594

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8b4c2d9e6f10'
down_revision: str | Sequence[str] | None = '1edcff27d5af'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "screenings",
        sa.Column("job_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_screenings_job_id_jobs",
        "screenings",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_screenings_job_id",
        "screenings",
        ["job_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_screenings_job_id",
        "screenings",
        type_="unique",
    )
    op.drop_constraint(
        "fk_screenings_job_id_jobs",
        "screenings",
        type_="foreignkey",
    )
    op.drop_column("screenings", "job_id")
