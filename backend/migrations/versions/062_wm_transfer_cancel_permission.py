"""062 — Grant WM transfer:cancel permission.

WM (Warehouse Manager) can create, submit, dispatch, and receive transfers
but was missing transfer:cancel — RM already has it, but WM cannot cancel
their own DRAFT/PENDING/APPROVED transfers, which surfaces as a spurious
RBAC_DENIED instead of the expected state-machine guard on invalid
transitions (see CLAUDE.md test coverage for the transfer cancel flow).

Revision ID: 062
Revises:     061
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
        VALUES ('WM', 'transfer:cancel', 'FULL', true)
        ON CONFLICT (role_code, action_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE role_code = 'WM' AND action_id = 'transfer:cancel'"
    )
