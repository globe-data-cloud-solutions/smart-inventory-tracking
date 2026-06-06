"""042 — grant WM and LM audit:view_logs (facility-scoped)

WM and LM need to view the audit log for their own facility. The endpoint
enforces scope automatically (see routers/audit_log.py: _SCOPE_CLAUSE) — they
only see their own actions plus transfers/adjustments at their assigned node.
"""

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO role_permissions (role_code, action_id, grant_type)
        VALUES
            ('WM', 'audit:view_logs', 'FULL'),
            ('LM', 'audit:view_logs', 'FULL')
        ON CONFLICT (role_code, action_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions
        WHERE role_code IN ('WM', 'LM') AND action_id = 'audit:view_logs'
    """)
