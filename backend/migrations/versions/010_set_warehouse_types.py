"""Set warehouse_type for the 12 warehouses inserted by seed_demo_data.py.

Revision ID: 010
Revises: 009
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None

# DB enum warehouse_type: FACTORY | REGIONAL | RETAIL | SUBCENTER
# Mapping from logical role: FACTORY=MWH, REGIONAL=RWH, RETAIL=WH, SUBCENTER=SUB_WH
_WH_TYPES = [
    # Addis Water
    ("20000001-a000-0000-0000-000000000001", "FACTORY"),  # Main Production Center
    ("20000001-a000-0000-0000-000000000002", "RETAIL"),  # North WH
    ("20000001-a000-0000-0000-000000000003", "SUBCENTER"),  # North-Subcenter WH
    ("20000001-a000-0000-0000-000000000004", "RETAIL"),  # South WH
    ("20000001-a000-0000-0000-000000000005", "RETAIL"),  # East WH
    ("20000001-a000-0000-0000-000000000006", "RETAIL"),  # West WH
    # Muger Cement — both production centers are main (FACTORY)
    ("20000002-0c00-0000-0000-000000000001", "FACTORY"),  # Harar Production Center
    ("20000002-0c00-0000-0000-000000000002", "FACTORY"),  # Ambo Production Center
    ("20000002-0c00-0000-0000-000000000003", "RETAIL"),  # Kombolcha WH
    ("20000002-0c00-0000-0000-000000000004", "RETAIL"),  # Mekele WH
    ("20000002-0c00-0000-0000-000000000005", "RETAIL"),  # Dire Dawa WH
    ("20000002-0c00-0000-0000-000000000006", "RETAIL"),  # Hawassa WH
]


def upgrade() -> None:
    for wh_id, wh_type in _WH_TYPES:
        op.execute(
            f"UPDATE warehouses SET warehouse_type = '{wh_type}' WHERE id = '{wh_id}'"
        )


def downgrade() -> None:
    for wh_id, _ in _WH_TYPES:
        op.execute(f"UPDATE warehouses SET warehouse_type = NULL WHERE id = '{wh_id}'")
