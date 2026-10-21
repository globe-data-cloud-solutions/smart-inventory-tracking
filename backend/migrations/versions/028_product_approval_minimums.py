"""add product_approval_minimums table for per-product authority floor overrides

SA/TA/NM can set a minimum authority level required to approve a specific product
for a given transaction type, overriding the standard tenant-level quantity bands.

Fallback chain (ApprovalService.get_required_approver):
  1. product_approval_minimums  (product + tx_type authority floor)
  2. product-level approval_rule (approval_rule.product_id = this product)
  3. tenant-level approval_rule  (approval_rule.product_id IS NULL)
  4. org-type hardcoded default  (ApprovalService._ORG_TYPE_DEFAULTS)

Revision ID: 028
Revises:     027
Create Date: 2026-05-29

Round-trip tested: alembic upgrade head → downgrade -1 → upgrade head
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_approval_minimums",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "transaction_type IN ('PULL','PUSH','SISTER','ADJUSTMENT','RECEIVE','ISSUE')",
            name="ck_pam_tx_type",
        ),
        # 1 = executive (SA/TA/NM), 2 = RM, 3 = LM, 4 = WM, 5 = reserved
        sa.Column("min_authority_level", sa.Integer, nullable=False),
        sa.CheckConstraint(
            "min_authority_level BETWEEN 1 AND 5",
            name="ck_pam_authority_level",
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "product_id", "transaction_type", name="uq_pam_product_tx_type"
        ),
    )

    # tenant_id leads both indexes per CLAUDE.md §7 index rule
    op.create_index(
        "idx_pam_tenant_product",
        "product_approval_minimums",
        ["tenant_id", "product_id"],
    )
    op.create_index(
        "idx_pam_tenant_tx_type",
        "product_approval_minimums",
        ["tenant_id", "transaction_type"],
    )

    op.execute("ALTER TABLE product_approval_minimums ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_approval_minimums "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON product_approval_minimums")
    op.execute("ALTER TABLE product_approval_minimums DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_pam_tenant_tx_type", table_name="product_approval_minimums")
    op.drop_index("idx_pam_tenant_product", table_name="product_approval_minimums")
    op.drop_table("product_approval_minimums")
