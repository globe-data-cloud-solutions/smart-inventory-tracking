"""095 — report grants by role and the report filter-options permission (2026-10-22).

Decided by Alex 2026-10-22:
  - AU is read-only on every report.
  - WM, LM, SA_GT and RT see their own node and the nodes below it (subtree
    scope, resolved in the route by resolve_node_scope).
  - TA and NM are tenant-wide; RM sees its region.

Grants added here (ON CONFLICT DO NOTHING, so existing rows are untouched):
  report:inventory_valuation  RM, WM, LM, SA_GT, RT   FULL
  report:stock_movement       WM, LM, SA_GT, RT       FULL
  report:expiry_alerts        LM, SA_GT, RT           FULL
  report:filter_options       TA, NM, RM, WM, LM, SA_GT, RT, SA   FULL
  report:filter_options       AU                      READ_ONLY

The filter-options action is new (REPORT_FILTER_OPTIONS in registry.py). Its
grants live in this migration and in scripts/seed_permissions.py.

Revision ID: 095
Revises: 094
"""

from __future__ import annotations

from alembic import op

revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None

# (role_code, action_id, grant_type)
_GRANTS: list[tuple[str, str, str]] = [
    ("RM", "report:inventory_valuation", "FULL"),
    ("RM", "report:filter_options", "FULL"),
    ("WM", "report:inventory_valuation", "FULL"),
    ("WM", "report:stock_movement", "FULL"),
    ("WM", "report:filter_options", "FULL"),
    ("LM", "report:inventory_valuation", "FULL"),
    ("LM", "report:stock_movement", "FULL"),
    ("LM", "report:expiry_alerts", "FULL"),
    ("LM", "report:filter_options", "FULL"),
    ("SA_GT", "report:inventory_valuation", "FULL"),
    ("SA_GT", "report:stock_movement", "FULL"),
    ("SA_GT", "report:expiry_alerts", "FULL"),
    ("SA_GT", "report:filter_options", "FULL"),
    ("RT", "report:inventory_valuation", "FULL"),
    ("RT", "report:stock_movement", "FULL"),
    ("RT", "report:expiry_alerts", "FULL"),
    ("RT", "report:filter_options", "FULL"),
    ("TA", "report:filter_options", "FULL"),
    ("NM", "report:filter_options", "FULL"),
    ("SA", "report:filter_options", "FULL"),
    ("AU", "report:filter_options", "READ_ONLY"),
]


def upgrade() -> None:
    for role_code, action_id, grant_type in _GRANTS:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
            VALUES ('{role_code}', '{action_id}', '{grant_type}', true)
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    for role_code, action_id, _ in _GRANTS:
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = '{role_code}' "
            f"AND action_id = '{action_id}'"
        )
