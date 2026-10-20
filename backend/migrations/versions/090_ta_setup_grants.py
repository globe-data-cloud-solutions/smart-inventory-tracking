"""090 — TA setup grants: positions, transfer config, adjustment submit.

TenantClaude18 E2E testing (ClaudeE2EReviewBug.md, Bugs 1-3) found that no
tenant-side role — including TA — could ever create an organization
position, configure a transfer type or approval rule, or submit an
adjustment. TA is the role meant to own tenant setup (positions, org
levels, approvals), so this adds, all grant_type FULL:

    position:manage               -> TA
    transfer_type:manage          -> TA
    transfer_approval_rule:manage -> TA
    transfer_approval_rule:view   -> TA
    adjustment:submit             -> TA

transfer_approval_rule:view is a necessary companion to :manage, not an
independent bug fix: upsert_approval_rules() (routers/transfer_types.py)
builds its response by calling list_approval_rules() directly as a plain
function, which re-runs that function's own @require_permission(...VIEW)
check against the caller on every call — so TA could POST a rule but the
same request would still 403 trying to build the response. Confirmed live
against TenantClaude18 while verifying this migration.

All five action ids already exist in registry.py (not new registrations)
and are correctly absent from read_only.py's READ_ACTIONS/
ALLOWED_WRITE_ACTIONS — genuine writes/view, blocked (or exempt, for the
view) by the fail-closed default under a READ_ONLY contract stage, which
is correct; no read-only reclassification needed.

ON CONFLICT DO NOTHING; downgrade deletes only the five rows added here.

Revision ID: 090
Revises:     089
Create Date: 2026-10-19

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
        VALUES
            ('TA', 'position:manage',               'FULL', true),
            ('TA', 'transfer_type:manage',           'FULL', true),
            ('TA', 'transfer_approval_rule:manage',  'FULL', true),
            ('TA', 'transfer_approval_rule:view',    'FULL', true),
            ('TA', 'adjustment:submit',              'FULL', true)
        ON CONFLICT (role_code, action_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE (role_code, action_id) IN (
            ('TA', 'position:manage'),
            ('TA', 'transfer_type:manage'),
            ('TA', 'transfer_approval_rule:manage'),
            ('TA', 'transfer_approval_rule:view'),
            ('TA', 'adjustment:submit')
        )
        """
    )
