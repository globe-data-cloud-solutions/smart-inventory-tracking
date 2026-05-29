"""seed tenant:view permission for all tenant-operational roles

GET /api/v1/tenants/{slug} is called on every page (dashboard, warehouses,
settings, personnel) to resolve the tenant's display name and org-type.
Only SA and TA had tenant:view, so NM/RM/WM/LM/SA_GT/RT/AU users received
HTTP 403 on every page load.

The tenant_id ABAC constraint in check_permission already enforces that a
user can only read their own tenant — adding tenant:view to lower roles does
not open cross-tenant access.

Revision ID: 026
Revises:     025
Create Date: 2026-05-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None

# Roles that need self-tenant read access (TA and SA already have it from earlier seeds)
_ROLES = ("NM", "RM", "WM", "LM", "SA_GT", "RT", "AU")


def upgrade() -> None:
    conn = op.get_bind()
    for role in _ROLES:
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_code, action_id, grant_type) "
                "VALUES (:r, 'tenant:view', 'FULL') "
                "ON CONFLICT (role_code, action_id) DO NOTHING"
            ),
            {"r": role},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for role in _ROLES:
        conn.execute(
            sa.text(
                "DELETE FROM role_permissions "
                "WHERE role_code = :r AND action_id = 'tenant:view'"
            ),
            {"r": role},
        )
