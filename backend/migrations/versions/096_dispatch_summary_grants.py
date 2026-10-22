"""096 — grants for the Dispatch Summary report (2026-10-22).

Agreed 2026-10-22: AU read-only; WM, LM, SA_GT and RT see their own node and
the nodes below it (subtree scope, resolved in the route). TA, NM and RM
already hold report:dispatch_summary in the seed matrix.

Grants added here (ON CONFLICT DO NOTHING):
  report:dispatch_summary  WM, LM, SA_GT, RT  FULL

Revision ID: 096
Revises: 095
"""

from __future__ import annotations

from alembic import op

revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None

_ROLES = ["WM", "LM", "SA_GT", "RT"]


def upgrade() -> None:
    for role_code in _ROLES:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
            VALUES ('{role_code}', 'report:dispatch_summary', 'FULL', true)
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    for role_code in _ROLES:
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = '{role_code}' "
            "AND action_id = 'report:dispatch_summary'"
        )
