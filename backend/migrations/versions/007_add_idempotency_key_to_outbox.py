"""add idempotency_key column to outbox table

Adds a VARCHAR(255) idempotency_key column to the outbox table so callers
can supply a deduplication key at write time, enabling true end-to-end
duplicate suppression for Celery task dispatch.

Design decisions:
  - Nullable: existing rows receive NULL.  Callers that don't need
    deduplication can continue to omit the argument.
  - Unique partial index WHERE idempotency_key IS NOT NULL: two outbox rows
    with the same non-NULL key are rejected by the DB; multiple NULL-key rows
    are allowed (NULL != NULL in SQL unique semantics).
  - The UUID primary key continues to serve as the Celery task id for rows
    that carry no explicit key.
  - No backfill required: NULL values on existing rows are valid and expected.

Revision ID: 007
Revises: 006
Create Date: 2026-05-17

Round-trip tested: alembic upgrade head → downgrade -1 → upgrade head
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox",
        sa.Column("idempotency_key", sa.String(255), nullable=True),
    )
    # Partial unique index: NULLs are excluded so multiple NULL-key rows coexist,
    # but two rows with the SAME non-NULL key raise a UniqueViolation (→ 409 in app).
    op.create_index(
        "idx_outbox_idempotency_key",
        "outbox",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_outbox_idempotency_key", table_name="outbox")
    op.drop_column("outbox", "idempotency_key")
