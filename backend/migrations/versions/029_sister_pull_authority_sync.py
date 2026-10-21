"""sync SISTER approval_rule authority fields from matching PULL rows

SISTER transfers share the same approval authority structure as PULL transfers
(PRD-APPENDIX §B9 — peer transfers follow pull-side routing).  For each SISTER
row, copy authority_level, auto_approve, and notify_levels from the PULL row
with the same tenant and approver_role.

Rows with no matching PULL counterpart keep the migration 027 defaults
(authority_level derived from role, auto_approve=false, notify_levels={}).

Revision ID: 029
Revises:     028
Create Date: 2026-05-29

Round-trip tested: alembic upgrade head → downgrade -1 → upgrade head
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None

_SYNC_SQL = """
    UPDATE approval_rule AS s
    SET
        authority_level = p.authority_level,
        auto_approve    = p.auto_approve,
        notify_levels   = p.notify_levels
    FROM approval_rule AS p
    WHERE s.transaction_type = 'SISTER'
      AND p.transaction_type = 'PULL'
      AND s.tenant_id        = p.tenant_id
      AND s.approver_role    = p.approver_role
"""

# Downgrade: restore SISTER rows to the per-role defaults set by migration 027
_RESET_SQL = """
    UPDATE approval_rule
    SET
        authority_level = CASE approver_role
            WHEN 'SA' THEN 1
            WHEN 'TA' THEN 1
            WHEN 'NM' THEN 1
            WHEN 'RM' THEN 2
            WHEN 'LM' THEN 3
            WHEN 'WM' THEN 4
            ELSE 4
        END,
        auto_approve  = false,
        notify_levels = '{}'
    WHERE transaction_type = 'SISTER'
"""


def upgrade() -> None:
    op.execute(sa.text(_SYNC_SQL))


def downgrade() -> None:
    op.execute(sa.text(_RESET_SQL))
