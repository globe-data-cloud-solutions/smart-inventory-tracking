"""053 — product_approval_minimums.product_id FK: ON DELETE CASCADE

migration 028 created product_approval_minimums.product_id as
FOREIGN KEY ... REFERENCES products(id) with the default NO ACTION
delete rule. When a product is deleted without first deleting its
product_approval_minimums rows (any code path other than the
CASCADE_TABLES-ordered test-tenant cleanup), the rows become orphaned
references rather than being rejected or removed — 18 such orphans
were found in the dev DB and removed as a one-time cleanup alongside
this migration.

Changes product_id (and the row's own tenant_id FK, for consistency
with the rest of the cascade chain) to ON DELETE CASCADE so deleting a
product always removes its approval-minimums rows.

Revision ID: 053
Revises:     052
Create Date: 2026-06-14

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE product_approval_minimums
            DROP CONSTRAINT product_approval_minimums_product_id_fkey,
            ADD  CONSTRAINT product_approval_minimums_product_id_fkey
                 FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    """)
    op.execute("""
        ALTER TABLE product_approval_minimums
            DROP CONSTRAINT product_approval_minimums_tenant_id_fkey,
            ADD  CONSTRAINT product_approval_minimums_tenant_id_fkey
                 FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE product_approval_minimums
            DROP CONSTRAINT product_approval_minimums_product_id_fkey,
            ADD  CONSTRAINT product_approval_minimums_product_id_fkey
                 FOREIGN KEY (product_id) REFERENCES products(id)
    """)
    op.execute("""
        ALTER TABLE product_approval_minimums
            DROP CONSTRAINT product_approval_minimums_tenant_id_fkey,
            ADD  CONSTRAINT product_approval_minimums_tenant_id_fkey
                 FOREIGN KEY (tenant_id) REFERENCES tenants(id)
    """)
