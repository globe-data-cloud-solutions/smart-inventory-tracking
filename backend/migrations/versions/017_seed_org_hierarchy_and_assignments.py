"""Seed organization_node, tenant_hierarchy_config, org_node_hierarchy, and
user_facility_assignments for the two demo tenants.

Uses the same warehouse UUIDs as seed_demo_data.py so that users.warehouse_id
remains valid as an organization_node.id reference.

Hierarchy layout:
  Tenant 1 — Addis Water (3 levels):
    Level 1 (NM):  Main Production Center  [FACTORY]
    Level 2 (WM):  North WH, South WH, East WH, West WH  [RETAIL]
    Level 3 (WM):  North-Subcenter WH  [SUBCENTER]

  Tenant 2 — Muger Cement (2 levels):
    Level 1 (NM):  Harar Production Center, Ambo Production Center  [FACTORY]
    Level 2 (WM):  Kombolcha WH, Mekele WH, Dire Dawa WH, Hawassa WH  [RETAIL]

These demo tenants are only created by scripts/seed_demo_data.py, never by a
migration — on a fresh database (e.g. CI) neither tenant row exists yet, and
every INSERT below would violate the tenant_id foreign key. Each tenant's
seed block is guarded on that tenant already existing.

Revision ID: 017
Revises: 016
Create Date: 2026-05-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None

# ── Tenant IDs ────────────────────────────────────────────────────────────────
_T1 = "10000001-0000-0000-0000-000000000001"  # Addis Water
_T2 = "10000002-0000-0000-0000-000000000001"  # Muger Cement

# ── Warehouse / organization_node IDs (match seed_demo_data.py) ───────────────
# Addis Water nodes
_T1_MAIN  = "20000001-a000-0000-0000-000000000001"  # Main Production Center
_T1_NORTH = "20000001-a000-0000-0000-000000000002"  # North WH
_T1_NSUB  = "20000001-a000-0000-0000-000000000003"  # North-Subcenter WH
_T1_SOUTH = "20000001-a000-0000-0000-000000000004"  # South WH
_T1_EAST  = "20000001-a000-0000-0000-000000000005"  # East WH
_T1_WEST  = "20000001-a000-0000-0000-000000000006"  # West WH

# Muger Cement nodes
_T2_HARAR    = "20000002-0c00-0000-0000-000000000001"  # Harar Production Center
_T2_AMBO     = "20000002-0c00-0000-0000-000000000002"  # Ambo Production Center
_T2_KOMBOLCHA= "20000002-0c00-0000-0000-000000000003"  # Kombolcha WH
_T2_MEKELE   = "20000002-0c00-0000-0000-000000000004"  # Mekele WH
_T2_DIREDAWA = "20000002-0c00-0000-0000-000000000005"  # Dire Dawa WH
_T2_HAWASSA  = "20000002-0c00-0000-0000-000000000006"  # Hawassa WH

# ── User IDs (match seed_demo_data.py) ────────────────────────────────────────
# Addis Water users
_U_AW_TA  = "00000001-a001-0000-0000-000000000001"  # TA  — no warehouse
_U_AW_NM  = "00000001-a002-0000-0000-000000000001"  # NM  — Main Production Center
_U_AW_WM1 = "00000001-a003-0000-0000-000000000001"  # WM  — North WH
_U_AW_WM2 = "00000001-a004-0000-0000-000000000001"  # WM  — North-Subcenter WH
_U_AW_WM3 = "00000001-a005-0000-0000-000000000001"  # WM  — South WH
_U_AW_WM4 = "00000001-a006-0000-0000-000000000001"  # WM  — East WH
_U_AW_WM5 = "00000001-a007-0000-0000-000000000001"  # WM  — West WH

# Muger Cement users
_U_MC_TA  = "00000002-0c01-0000-0000-000000000001"  # TA  — no warehouse
_U_MC_NM1 = "00000002-0c02-0000-0000-000000000001"  # NM  — Harar Production Center
_U_MC_NM2 = "00000002-0c03-0000-0000-000000000001"  # NM  — Ambo Production Center
_U_MC_WM1 = "00000002-0c04-0000-0000-000000000001"  # WM  — Kombolcha WH
_U_MC_WM2 = "00000002-0c05-0000-0000-000000000001"  # WM  — Mekele WH
_U_MC_WM3 = "00000002-0c06-0000-0000-000000000001"  # WM  — Dire Dawa WH
_U_MC_WM4 = "00000002-0c07-0000-0000-000000000001"  # WM  — Hawassa WH

# SA user — seeded in T1 context but is platform-wide
_U_SA     = "00000001-0a00-0000-0000-000000000001"

# ── System user for created_by on seeded records ──────────────────────────────
_SYS_USER = "00000000-0000-0000-0000-000000000001"


def _tenant_exists(bind: sa.engine.Connection, tenant_id: str) -> bool:
    return bind.execute(
        sa.text("SELECT 1 FROM tenants WHERE id = :tid"), {"tid": tenant_id}
    ).first() is not None


def upgrade() -> None:
    # ── RLS context: disable for seed (system migration, not tenant request) ──
    op.execute("SELECT set_config('app.current_tenant_id', '', false)")

    bind = op.get_bind()
    t1_exists = _tenant_exists(bind, _T1)
    t2_exists = _tenant_exists(bind, _T2)
    if not t1_exists:
        print(f"017: demo tenant {_T1} absent — seed skipped")
    if not t2_exists:
        print(f"017: demo tenant {_T2} absent — seed skipped")

    # ── tenant_hierarchy_config ───────────────────────────────────────────────
    # Addis Water: 3 levels
    if t1_exists:
        op.execute(f"""
            INSERT INTO tenant_hierarchy_config
                (tenant_id, level_number, level_name, default_role_code, role_display_label,
                 is_stock_holding, is_active)
            VALUES
              ('{_T1}', 1, 'Production Center', 'NM', 'Production Manager',   true,  true),
              ('{_T1}', 2, 'Regional Warehouse', 'WM', 'Warehouse Manager',    true,  true),
              ('{_T1}', 3, 'Sub-Warehouse',      'WM', 'Sub-Warehouse Manager',true,  true)
            ON CONFLICT (tenant_id, level_number) DO NOTHING
        """)

        # ── organization_node — Addis Water nodes ─────────────────────────────
        # Uses the same IDs as the warehouses table so users.warehouse_id is valid here too.
        op.execute(f"""
            INSERT INTO organization_node
                (id, tenant_id, name, code, hierarchy_level, parent_node_id, is_stock_holding, is_active)
            VALUES
              ('{_T1_MAIN}',  '{_T1}', 'Main Production Center', 'AW-MAIN',  1, NULL,        true, true),
              ('{_T1_NORTH}', '{_T1}', 'North WH',               'AW-NORTH', 2, NULL,        true, true),
              ('{_T1_NSUB}',  '{_T1}', 'North-Subcenter WH',     'AW-NSUB',  3, '{_T1_NORTH}',true,true),
              ('{_T1_SOUTH}', '{_T1}', 'South WH',               'AW-SOUTH', 2, NULL,        true, true),
              ('{_T1_EAST}',  '{_T1}', 'East WH',                'AW-EAST',  2, NULL,        true, true),
              ('{_T1_WEST}',  '{_T1}', 'West WH',                'AW-WEST',  2, NULL,        true, true)
            ON CONFLICT (id) DO NOTHING
        """)

        # ── org_node_hierarchy — PRIMARY_REPORTS_TO — Addis Water ─────────────
        # Level-2 WHs report to Main Production Center; level-3 sub-WH reports to North WH.
        op.execute(f"""
            INSERT INTO org_node_hierarchy
                (tenant_id, from_node_id, to_node_id, relationship_type, is_preferred)
            VALUES
              ('{_T1}', '{_T1_NORTH}', '{_T1_MAIN}',  'PRIMARY_REPORTS_TO', false),
              ('{_T1}', '{_T1_SOUTH}', '{_T1_MAIN}',  'PRIMARY_REPORTS_TO', false),
              ('{_T1}', '{_T1_EAST}',  '{_T1_MAIN}',  'PRIMARY_REPORTS_TO', false),
              ('{_T1}', '{_T1_WEST}',  '{_T1_MAIN}',  'PRIMARY_REPORTS_TO', false),
              ('{_T1}', '{_T1_NSUB}',  '{_T1_NORTH}', 'PRIMARY_REPORTS_TO', false)
            ON CONFLICT DO NOTHING
        """)

        # ── org_node_hierarchy — SUPPLY_FROM — Addis Water ────────────────────
        # WHs pull from Main Production Center by default.
        op.execute(f"""
            INSERT INTO org_node_hierarchy
                (tenant_id, from_node_id, to_node_id, relationship_type, is_preferred)
            VALUES
              ('{_T1}', '{_T1_NORTH}', '{_T1_MAIN}',  'SUPPLY_FROM', true),
              ('{_T1}', '{_T1_SOUTH}', '{_T1_MAIN}',  'SUPPLY_FROM', true),
              ('{_T1}', '{_T1_EAST}',  '{_T1_MAIN}',  'SUPPLY_FROM', true),
              ('{_T1}', '{_T1_WEST}',  '{_T1_MAIN}',  'SUPPLY_FROM', true),
              ('{_T1}', '{_T1_NSUB}',  '{_T1_NORTH}', 'SUPPLY_FROM', true)
            ON CONFLICT DO NOTHING
        """)

        # ── user_facility_assignments — Addis Water WMs ───────────────────────
        # TA users have no warehouse — skip them (they operate tenant-wide via role).
        op.execute(f"""
            INSERT INTO user_facility_assignments
                (tenant_id, user_id, facility_id, assignment_type, role_code,
                 valid_from, valid_until, created_by, is_active)
            VALUES
              ('{_T1}', '{_U_AW_NM}',  '{_T1_MAIN}',  'PRIMARY', 'NM', now(), NULL, '{_SYS_USER}', true),
              ('{_T1}', '{_U_AW_WM1}', '{_T1_NORTH}', 'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true),
              ('{_T1}', '{_U_AW_WM2}', '{_T1_NSUB}',  'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true),
              ('{_T1}', '{_U_AW_WM3}', '{_T1_SOUTH}', 'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true),
              ('{_T1}', '{_U_AW_WM4}', '{_T1_EAST}',  'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true),
              ('{_T1}', '{_U_AW_WM5}', '{_T1_WEST}',  'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true)
            ON CONFLICT DO NOTHING
        """)

    # Muger Cement: 2 levels
    if t2_exists:
        op.execute(f"""
            INSERT INTO tenant_hierarchy_config
                (tenant_id, level_number, level_name, default_role_code, role_display_label,
                 is_stock_holding, is_active)
            VALUES
              ('{_T2}', 1, 'Production Center', 'NM', 'Production Manager', true, true),
              ('{_T2}', 2, 'Regional Warehouse','WM', 'Warehouse Manager',  true, true)
            ON CONFLICT (tenant_id, level_number) DO NOTHING
        """)

        # ── organization_node — Muger Cement nodes ────────────────────────────
        op.execute(f"""
            INSERT INTO organization_node
                (id, tenant_id, name, code, hierarchy_level, parent_node_id, is_stock_holding, is_active)
            VALUES
              ('{_T2_HARAR}',     '{_T2}', 'Harar Production Center', 'MC-HARAR', 1, NULL, true, true),
              ('{_T2_AMBO}',      '{_T2}', 'Ambo Production Center',  'MC-AMBO',  1, NULL, true, true),
              ('{_T2_KOMBOLCHA}', '{_T2}', 'Kombolcha WH',            'MC-KOM',   2, NULL, true, true),
              ('{_T2_MEKELE}',    '{_T2}', 'Mekele WH',               'MC-MEK',   2, NULL, true, true),
              ('{_T2_DIREDAWA}',  '{_T2}', 'Dire Dawa WH',            'MC-DDW',   2, NULL, true, true),
              ('{_T2_HAWASSA}',   '{_T2}', 'Hawassa WH',              'MC-HAW',   2, NULL, true, true)
            ON CONFLICT (id) DO NOTHING
        """)

        # ── org_node_hierarchy — PRIMARY_REPORTS_TO — Muger Cement ────────────
        # Kombolcha+Mekele report to Harar; Dire Dawa+Hawassa report to Ambo.
        op.execute(f"""
            INSERT INTO org_node_hierarchy
                (tenant_id, from_node_id, to_node_id, relationship_type, is_preferred)
            VALUES
              ('{_T2}', '{_T2_KOMBOLCHA}', '{_T2_HARAR}', 'PRIMARY_REPORTS_TO', false),
              ('{_T2}', '{_T2_MEKELE}',    '{_T2_HARAR}', 'PRIMARY_REPORTS_TO', false),
              ('{_T2}', '{_T2_DIREDAWA}',  '{_T2_AMBO}',  'PRIMARY_REPORTS_TO', false),
              ('{_T2}', '{_T2_HAWASSA}',   '{_T2_AMBO}',  'PRIMARY_REPORTS_TO', false)
            ON CONFLICT DO NOTHING
        """)

        # ── org_node_hierarchy — SUPPLY_FROM — Muger Cement ───────────────────
        # WHs pull from their respective production centers.
        op.execute(f"""
            INSERT INTO org_node_hierarchy
                (tenant_id, from_node_id, to_node_id, relationship_type, is_preferred)
            VALUES
              ('{_T2}', '{_T2_KOMBOLCHA}', '{_T2_HARAR}', 'SUPPLY_FROM', true),
              ('{_T2}', '{_T2_MEKELE}',    '{_T2_HARAR}', 'SUPPLY_FROM', true),
              ('{_T2}', '{_T2_DIREDAWA}',  '{_T2_AMBO}',  'SUPPLY_FROM', true),
              ('{_T2}', '{_T2_HAWASSA}',   '{_T2_AMBO}',  'SUPPLY_FROM', true)
            ON CONFLICT DO NOTHING
        """)

        # ── user_facility_assignments — Muger Cement NMs + WMs ────────────────
        op.execute(f"""
            INSERT INTO user_facility_assignments
                (tenant_id, user_id, facility_id, assignment_type, role_code,
                 valid_from, valid_until, created_by, is_active)
            VALUES
              ('{_T2}', '{_U_MC_NM1}', '{_T2_HARAR}',     'PRIMARY', 'NM', now(), NULL, '{_SYS_USER}', true),
              ('{_T2}', '{_U_MC_NM2}', '{_T2_AMBO}',      'PRIMARY', 'NM', now(), NULL, '{_SYS_USER}', true),
              ('{_T2}', '{_U_MC_WM1}', '{_T2_KOMBOLCHA}', 'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true),
              ('{_T2}', '{_U_MC_WM2}', '{_T2_MEKELE}',    'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true),
              ('{_T2}', '{_U_MC_WM3}', '{_T2_DIREDAWA}',  'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true),
              ('{_T2}', '{_U_MC_WM4}', '{_T2_HAWASSA}',   'PRIMARY', 'WM', now(), NULL, '{_SYS_USER}', true)
            ON CONFLICT DO NOTHING
        """)

    op.execute("SELECT set_config('app.current_tenant_id', '', false)")


def downgrade() -> None:
    # Clear by known tenant IDs — safe because RLS is bypassed with empty context
    op.execute("SELECT set_config('app.current_tenant_id', '', false)")

    # user_facility_assignments — delete seeded PRIMARY rows only
    op.execute(f"""
        DELETE FROM user_facility_assignments
        WHERE tenant_id IN ('{_T1}', '{_T2}')
          AND assignment_type = 'PRIMARY'
          AND created_by = '{_SYS_USER}'
    """)

    # org_node_hierarchy — delete seeded relationships
    op.execute(f"""
        DELETE FROM org_node_hierarchy
        WHERE tenant_id IN ('{_T1}', '{_T2}')
    """)

    # organization_node — delete seeded nodes (children before parents)
    op.execute(f"""
        DELETE FROM organization_node
        WHERE tenant_id IN ('{_T1}', '{_T2}')
    """)

    # tenant_hierarchy_config — delete seeded levels
    op.execute(f"""
        DELETE FROM tenant_hierarchy_config
        WHERE tenant_id IN ('{_T1}', '{_T2}')
    """)

    op.execute("SELECT set_config('app.current_tenant_id', '', false)")
