"""add slug to tenants

Revision ID: 019
Revises: 018
Create Date: 2026-05-27

"""
from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80]


def upgrade() -> None:
    conn = op.get_bind()

    # Add column only if it doesn't already exist (idempotent)
    cols = [r[0] for r in conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns "
                "WHERE table_name='tenants' AND column_name='slug'")
    ).fetchall()]
    if "slug" not in cols:
        op.add_column("tenants", sa.Column("slug", sa.String(100), nullable=True))

    # Add unique constraint only if it doesn't exist
    constraints = [r[0] for r in conn.execute(
        sa.text("SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_name='tenants' AND constraint_name='uq_tenants_slug'")
    ).fetchall()]
    if "uq_tenants_slug" not in constraints:
        op.create_unique_constraint("uq_tenants_slug", "tenants", ["slug"])

    # Backfill slugs for tenants that don't have one yet
    rows = conn.execute(sa.text("SELECT id, name FROM tenants WHERE slug IS NULL")).fetchall()
    seen: set[str] = set()
    # Collect existing slugs to avoid conflicts
    for r in conn.execute(sa.text("SELECT slug FROM tenants WHERE slug IS NOT NULL")).fetchall():
        seen.add(r[0])
    for row in rows:
        base = _slugify(row.name)
        slug = base
        suffix = 1
        while slug in seen:
            slug = f"{base}-{suffix}"
            suffix += 1
        seen.add(slug)
        conn.execute(
            sa.text("UPDATE tenants SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": str(row.id)},
        )


def downgrade() -> None:
    op.drop_constraint("uq_tenants_slug", "tenants", type_="unique")
    op.drop_column("tenants", "slug")
