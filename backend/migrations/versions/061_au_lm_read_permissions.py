"""061 — Grant AU read-only access + LM transfer:list/receive/adjustment grants.

AU (Auditor) is documented as "Read Only / Auditor" with full read access to
all operational data tenant-wide and no write access. The live role_permissions
table only carried audit/report/analytics read grants — it was missing basic
read visibility into inventory balances, transfers, adjustments, products, and
approval-rule configuration. This migration closes that gap with READ_ONLY
grants (all confirmed to exist in backend/shared/permissions/registry.py).

LM (Logistics Manager) already has transfer:dispatch and transfer:view but was
missing transfer:list (cannot list transfers, only fetch one by id) and
transfer:receive (LM receives stock at their assigned node — ABAC node scope
is enforced separately in check_permission(), this is the RBAC grant only).
Also missing adjustment:list/adjustment:view for visibility into adjustments
at their node.

Revision ID: 061
Revises:     060
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None

AU_GRANTS: tuple[tuple[str, str], ...] = (
    ("inventory:view_balance", "READ_ONLY"),
    ("inventory:view", "READ_ONLY"),
    ("transfer:list", "READ_ONLY"),
    ("transfer:view", "READ_ONLY"),
    ("adjustment:list", "READ_ONLY"),
    ("adjustment:view", "READ_ONLY"),
    ("product:list", "READ_ONLY"),
    ("product:view", "READ_ONLY"),
    ("tenant:self_approval_view", "READ_ONLY"),
    ("transfer_approval_rule:view", "READ_ONLY"),
    ("adjustment_approval_rule:view", "READ_ONLY"),
    ("transfer_type:view", "READ_ONLY"),
    ("notification:view", "FULL"),
)

LM_GRANTS: tuple[tuple[str, str], ...] = (
    ("transfer:list", "READ_ONLY"),
    ("transfer:receive", "READ_ONLY"),
    ("adjustment:list", "READ_ONLY"),
    ("adjustment:view", "READ_ONLY"),
)


def upgrade() -> None:
    for action_id, grant_type in AU_GRANTS:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
            VALUES ('AU', '{action_id}', '{grant_type}', true)
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )
    for action_id, grant_type in LM_GRANTS:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
            VALUES ('LM', '{action_id}', '{grant_type}', true)
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    for action_id, _grant_type in AU_GRANTS:
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = 'AU' AND action_id = '{action_id}'"
        )
    for action_id, _grant_type in LM_GRANTS:
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = 'LM' AND action_id = '{action_id}'"
        )
