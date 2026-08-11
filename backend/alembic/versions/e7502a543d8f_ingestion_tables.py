"""ingestion_tables

Revision ID: e7502a543d8f
Revises: 1e152befd6b3
Create Date: 2026-07-22 02:03:26.110323

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7502a543d8f"
down_revision: str | Sequence[str] | None = "1e152befd6b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    # Extending Documents. Wrapped in IF NOT EXISTS via raw SQL because a prior
    # partial run may have added these columns before failing later in the
    # migration — alembic's transactional rollback doesn't always unwind them.
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS max_severity VARCHAR(16)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS acked_by UUID")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS acked_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS lexicon_version VARCHAR(32)")

    # Chunks, single source of truth for the citation gate
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(512), nullable=True),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("sha8", sa.String(8), nullable=False),
        sa.Column("qdrant_point_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_doc_index"),
    )

    op.create_table(
        "document_findings",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("sample_offsets", sa.JSON(), nullable=True),
        sa.Column("checksum_valid", sa.Boolean(), nullable=True),
    )

    # for detecting if prev model used for ingest is the same, or it has been changed
    op.create_table(
        "index_manifest",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("embed_model", sa.String(255), nullable=False),
        sa.Column("embed_dim", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    #
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress_pct", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("arq_job_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.execute(
        "INSERT INTO processing_status (id, name) "
        "SELECT gen_random_uuid(), 'blocked' "
        "WHERE NOT EXISTS (SELECT 1 FROM processing_status WHERE name = 'blocked')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM processing_status WHERE name = 'blocked'")
    op.drop_table("jobs")
    op.drop_table("index_manifest")
    op.drop_table("document_findings")
    op.drop_table("chunks")
    op.drop_column("documents", "lexicon_version")
    op.drop_column("documents", "acked_at")
    op.drop_column("documents", "acked_by")
    op.drop_column("documents", "max_severity")
