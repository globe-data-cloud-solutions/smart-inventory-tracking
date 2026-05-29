"""enhance approval_rule with authority levels, auto-approve, and RECEIVE/ISSUE support

Adds four columns to approval_rule:
  authority_level INTEGER  — numeric authority tier for the approver_role
                             (SA/TA/NM→1, RM→2, LM→3, WM→4)
  auto_approve    BOOLEAN  — true: band is auto-approved; higher levels notified only
  notify_levels   INT[]    — authority levels to notify when this band approves/rejects
  simple_mode     BOOLEAN  — true: rule applies across all transaction types (default)

Expands the transaction_type CHECK to include RECEIVE and ISSUE.
Backfills authority_level from approver_role for all existing rows.

Revision ID: 027
Revises:     026
Create Date: 2026-05-29

Round-trip tested: alembic upgrade head → downgrade -1 → upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None

# authority_level derivation — matches ApprovalService._ROLE_AUTHORITY_LEVEL
_BACKFILL_SQL = """
    UPDATE approval_rule
    SET authority_level = CASE approver_role
        WHEN 'SA' THEN 1
        WHEN 'TA' THEN 1
        WHEN 'NM' THEN 1
        WHEN 'RM' THEN 2
        WHEN 'LM' THEN 3
        WHEN 'WM' THEN 4
        ELSE 4
    END
"""


def upgrade() -> None:
    # 1. Drop old CHECK — it blocks RECEIVE/ISSUE values
    op.drop_constraint("ck_approval_rule_tx_type", "approval_rule", type_="check")

    # 2. Add new columns (nullable-free; server defaults handle existing rows)
    op.add_column(
        "approval_rule",
        sa.Column("authority_level", sa.Integer, nullable=False, server_default="4"),
    )
    op.add_column(
        "approval_rule",
        sa.Column("auto_approve", sa.Boolean, nullable=False, server_default="false"),
    )
    op.add_column(
        "approval_rule",
        sa.Column(
            "notify_levels",
            postgresql.ARRAY(sa.Integer),
            nullable=False,
            server_default=sa.text("'{}'::integer[]"),
        ),
    )
    op.add_column(
        "approval_rule",
        sa.Column("simple_mode", sa.Boolean, nullable=False, server_default="true"),
    )

    # 3. Re-add CHECK constraint with RECEIVE and ISSUE
    op.create_check_constraint(
        "ck_approval_rule_tx_type",
        "approval_rule",
        "transaction_type IN ('PULL','PUSH','SISTER','ADJUSTMENT','RECEIVE','ISSUE')",
    )

    # 4. Backfill authority_level from approver_role for all existing rows
    op.execute(sa.text(_BACKFILL_SQL))


def downgrade() -> None:
    # Remove expanded constraint before dropping RECEIVE/ISSUE rows
    op.drop_constraint("ck_approval_rule_tx_type", "approval_rule", type_="check")

    # Purge RECEIVE/ISSUE rows so original constraint can be re-added cleanly
    op.execute("DELETE FROM approval_rule WHERE transaction_type IN ('RECEIVE', 'ISSUE')")

    op.drop_column("approval_rule", "simple_mode")
    op.drop_column("approval_rule", "notify_levels")
    op.drop_column("approval_rule", "auto_approve")
    op.drop_column("approval_rule", "authority_level")

    op.create_check_constraint(
        "ck_approval_rule_tx_type",
        "approval_rule",
        "transaction_type IN ('PULL','PUSH','SISTER','ADJUSTMENT')",
    )
