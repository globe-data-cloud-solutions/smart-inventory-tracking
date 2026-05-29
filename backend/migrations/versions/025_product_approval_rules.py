"""add product_id to approval_rule for product-level approval overrides

PROMPT C — Product-level approval rules with tenant/org-type fallback.
Each product can override the tenant-level approval thresholds.
Existing rows (product_id NULL) remain tenant-level rules.
New rows with product_id set are product-level overrides.

Fallback chain (approval_service.get_required_approver):
  1. Product-level rule (product_id = this product)
  2. Tenant-level rule  (product_id IS NULL)
  3. Org-type default   (hardcoded in ApprovalService._ORG_TYPE_DEFAULTS)

Revision ID: 025
Revises:     024
Create Date: 2026-05-28

Round-trip tested: alembic upgrade head → downgrade -1 → upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None

# Roles that may view product approval rules (any operational role)
_VIEW_ROLES   = ("SA", "TA", "NM", "RM", "WM")
# Roles that may upsert/reset product approval rules (TA and NM per design, SA always)
_MANAGE_ROLES = ("SA", "TA", "NM")


def upgrade() -> None:
    # ── 1. Add product_id FK column to approval_rule ──────────────────────────
    op.add_column(
        "approval_rule",
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=True,
        ),
    )

    # ── 2. Partial unique index: one rule per (product, tx_type, band order) ──
    # Uses approval_order as the band identifier so each product can override
    # each approval band exactly once per transaction type.
    op.create_index(
        "idx_approval_rule_product_band",
        "approval_rule",
        ["tenant_id", "transaction_type", "approval_order", "product_id"],
        unique=True,
        postgresql_where=sa.text("product_id IS NOT NULL"),
    )

    # ── 3. Seed role_permissions for new product approval-rule actions ─────────
    conn = op.get_bind()

    for role in _VIEW_ROLES:
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_code, action_id, grant_type) "
                "VALUES (:r, 'product:view_approval_rules', 'FULL') "
                "ON CONFLICT (role_code, action_id) DO NOTHING"
            ),
            {"r": role},
        )

    for role in _MANAGE_ROLES:
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_code, action_id, grant_type) "
                "VALUES (:r, 'product:manage_approval_rules', 'FULL') "
                "ON CONFLICT (role_code, action_id) DO NOTHING"
            ),
            {"r": role},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove seeded role_permissions
    conn.execute(
        sa.text(
            "DELETE FROM role_permissions "
            "WHERE action_id IN ('product:view_approval_rules', 'product:manage_approval_rules')"
        )
    )

    op.drop_index("idx_approval_rule_product_band", table_name="approval_rule")
    op.drop_column("approval_rule", "product_id")
