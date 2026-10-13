"""084 — Dispatch override grants for WM / RM / NM / TA.

Phase C of the dispatch engine lets the final approver change the suggested
lot order (dispatch:fefo_override) and pick lots by hand (dispatch:lot_select).
Until now only SA held both; RM held a CONDITIONAL fefo_override and WM held
lot_select. This adds, all grant_type FULL:

    dispatch:fefo_override -> WM, NM, TA
    dispatch:lot_select    -> RM, NM, TA

RM's existing CONDITIONAL fefo_override, WM's lot_select and SA are untouched
(ON CONFLICT DO NOTHING; downgrade deletes only the six rows added here).

Revision ID: 084
Revises:     083
Create Date: 2026-10-13

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
        VALUES
            ('WM', 'dispatch:fefo_override', 'FULL', true),
            ('NM', 'dispatch:fefo_override', 'FULL', true),
            ('TA', 'dispatch:fefo_override', 'FULL', true),
            ('RM', 'dispatch:lot_select',    'FULL', true),
            ('NM', 'dispatch:lot_select',    'FULL', true),
            ('TA', 'dispatch:lot_select',    'FULL', true)
        ON CONFLICT (role_code, action_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE (role_code, action_id) IN (
            ('WM', 'dispatch:fefo_override'),
            ('NM', 'dispatch:fefo_override'),
            ('TA', 'dispatch:fefo_override'),
            ('RM', 'dispatch:lot_select'),
            ('NM', 'dispatch:lot_select'),
            ('TA', 'dispatch:lot_select')
        )
        """
    )
