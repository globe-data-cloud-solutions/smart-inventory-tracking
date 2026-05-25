"""Fix warehouse_type for seeded warehouses — bypasses RLS via set_config.

Migration 010 ran without RLS context and its UPDATEs were silently blocked
by the RLS policy on the warehouses table (added in migration 002).
This migration sets app.current_tenant_id before each UPDATE so RLS allows
the write through. Uses transaction=False so we can commit the set_config
call before the UPDATE if needed, but single-session set_config with false
(not transaction-scoped) works within a single migration connection.

Revision ID: 011
Revises: 010
Create Date: 2026-05-25
"""
from __future__ import annotations

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

# Tenant 1 warehouses — Addis Ababa Water Treatment Works
_T1 = "10000001-0000-0000-0000-000000000001"
_T1_WH = [
    ("20000001-a000-0000-0000-000000000001", "FACTORY"),    # Main Production Center (MWH)
    ("20000001-a000-0000-0000-000000000002", "RETAIL"),     # North WH
    ("20000001-a000-0000-0000-000000000003", "SUBCENTER"),  # North-Subcenter WH
    ("20000001-a000-0000-0000-000000000004", "RETAIL"),     # South WH
    ("20000001-a000-0000-0000-000000000005", "RETAIL"),     # East WH
    ("20000001-a000-0000-0000-000000000006", "RETAIL"),     # West WH
]

# Tenant 2 warehouses — Harar Beverage
_T2 = "10000002-0000-0000-0000-000000000001"
_T2_WH = [
    ("20000002-0c00-0000-0000-000000000001", "FACTORY"),    # Harar Production Center (MWH)
    ("20000002-0c00-0000-0000-000000000002", "FACTORY"),    # Ambo Production Center (MWH)
    ("20000002-0c00-0000-0000-000000000003", "RETAIL"),     # Kombolcha WH
    ("20000002-0c00-0000-0000-000000000004", "RETAIL"),     # Mekele WH
    ("20000002-0c00-0000-0000-000000000005", "RETAIL"),     # Dire Dawa WH
    ("20000002-0c00-0000-0000-000000000006", "RETAIL"),     # Hawassa WH
]


def upgrade() -> None:
    # set_config with false = session-local (not transaction-scoped) so it persists
    # for the duration of this connection and satisfies the RLS policy on warehouses.
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_T1}', false)")
    for wh_id, wh_type in _T1_WH:
        op.execute(
            f"UPDATE warehouses SET warehouse_type = '{wh_type}' WHERE id = '{wh_id}'"
        )

    op.execute(f"SELECT set_config('app.current_tenant_id', '{_T2}', false)")
    for wh_id, wh_type in _T2_WH:
        op.execute(
            f"UPDATE warehouses SET warehouse_type = '{wh_type}' WHERE id = '{wh_id}'"
        )

    # Clear the context after we're done so subsequent statements aren't scoped
    op.execute("SELECT set_config('app.current_tenant_id', '', false)")


def downgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_T1}', false)")
    for wh_id, _ in _T1_WH:
        op.execute(f"UPDATE warehouses SET warehouse_type = NULL WHERE id = '{wh_id}'")

    op.execute(f"SELECT set_config('app.current_tenant_id', '{_T2}', false)")
    for wh_id, _ in _T2_WH:
        op.execute(f"UPDATE warehouses SET warehouse_type = NULL WHERE id = '{wh_id}'")

    op.execute("SELECT set_config('app.current_tenant_id', '', false)")
