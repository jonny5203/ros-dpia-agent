"""profile_tables

Revision ID: a1b2c3d4e5f6
Revises: e7502a543d8f
Create Date: 2026-07-28 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = 'e7502a543d8f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add project_profiles and prompt_versions tables."""

    # Prompt registry: every generation records which rendered prompt + version was used,
    # so reviewers can answer "what was the model told?".
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
    )

    # Project profile: JSONB holds the full Pydantic ProjectProfile (purpose, dataSubjects,
    # personalDataCategories, specialCategories, systems, processors, ...); one row per
    # analysis run, latest wins. model + prompt_version recorded for audit.
    op.create_table(
        "project_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False, index=True
        ),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("overall_confidence", sa.String(16), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("project_profiles")
    op.drop_table("prompt_versions")
