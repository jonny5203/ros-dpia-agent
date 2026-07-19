"""seed_lookup_tables

Revision ID: 1e152befd6b3
Revises: ebf8af4e02fc
Create Date: 2026-07-19 19:39:04.380145

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1e152befd6b3'
down_revision: str | Sequence[str] | None = 'ebf8af4e02fc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

classification = sa.table(
    "classification",
    sa.column("id", sa.Uuid),
    sa.column("name", sa.String),
)
embed = sa.table(
    "embed",
    sa.column("id", sa.Uuid),
    sa.column("model", sa.String),
    sa.column("dimension", sa.Integer),
)
processing_status = sa.table(
    "processing_status",
    sa.column("id", sa.Uuid),
    sa.column("name", sa.String),
)

def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(classification, [
        {"id": uuid.uuid4(), "name": "open"},
        {"id": uuid.uuid4(), "name": "restricted"},
        {"id": uuid.uuid4(), "name": "confidential"},
    ])
    op.bulk_insert(embed, [
        {"id": uuid.uuid4(), "model": "openai/text-embedding-3-large", "dimension": 3072},
    ])
    op.bulk_insert(processing_status, [
        {"id": uuid.uuid4(), "name": "pending"},
        {"id": uuid.uuid4(), "name": "parsing"},
        {"id": uuid.uuid4(), "name": "ready"},
        {"id": uuid.uuid4(), "name": "failed"},
    ])

def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM processing_status")
    op.execute("DELETE FROM embed")
    op.execute("DELETE FROM classification")
