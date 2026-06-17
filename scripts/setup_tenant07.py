"""
ONE-TIME SETUP SCRIPT — Tenant 07 (Test Organization Seven)
============================================================
Creates all test data for end-to-end testing:
  PART 1  — Tenant
  PART 2  — Hierarchy Config (4 levels)
  PART 3  — Org Nodes (14 nodes, 2 factory branches)
  PART 4  — Positions (2 per node + tenant-wide AU/LM)
  PART 5  — Users (all roles, password Test@2026)
  PART 6  — Products (5 products, 2 categories, 2 controlled)
  PART 7  — Transfer Type Config (PULL/PUSH/SISTER)
  PART 8  — Approval Rules (self-approval + transfer routing)
  PART 9  — Opening Stock (all Factory A + B warehouses)

Idempotent: safe to re-run — uses ON CONFLICT DO NOTHING /
fixed UUIDs so duplicate runs are no-ops.

Run:  python scripts/setup_tenant07.py
Requires: DATABASE_URL env var
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import date

# Force UTF-8 output on Windows (avoids cp1252 codec errors for non-ASCII chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# --Connection ─────────────────────────────────────────────────────────────────
engine = create_async_engine(os.environ["DATABASE_URL"])
Session = async_sessionmaker(bind=engine, expire_on_commit=False)

# --Fixed IDs — do not change after first run ──────────────────────────────────
T07_ID   = "07000007-0000-0000-0000-000000000001"
PLAN_ID  = "07000007-ffff-0000-0000-000000000001"
SA_USER  = "00000001-0a00-0000-0000-000000000001"  # seed_demo_data.py SA

# Org Nodes
NODE_FA    = "07000007-0001-0000-0000-000000000001"  # Factory A     (L1)
NODE_RA    = "07000007-0002-0000-0000-000000000001"  # Region A      (L2)
NODE_SRA   = "07000007-0003-0000-0000-000000000001"  # Subregion A   (L3)
NODE_WHA1  = "07000007-0004-0000-0000-000000000001"  # WHA1          (L4)
NODE_WHA2  = "07000007-0004-0000-0000-000000000002"  # WHA2          (L4)
NODE_WHA3  = "07000007-0004-0000-0000-000000000003"  # WHA3          (L4)
NODE_FB    = "07000007-0005-0000-0000-000000000001"  # Factory B     (L1)
NODE_RB1   = "07000007-0006-0000-0000-000000000001"  # Region B1     (L2)
NODE_SRB1  = "07000007-0007-0000-0000-000000000001"  # Subregion B1  (L3)
NODE_WHB11 = "07000007-0008-0000-0000-000000000001"  # WHB1-1        (L4)
NODE_WHB12 = "07000007-0008-0000-0000-000000000002"  # WHB1-2        (L4)
NODE_RB2   = "07000007-0009-0000-0000-000000000001"  # Region B2     (L2)
NODE_WHB21 = "07000007-000a-0000-0000-000000000001"  # WHB2-1        (L4, skips L3)
NODE_WHB22 = "07000007-000a-0000-0000-000000000002"  # WHB2-2        (L4, skips L3)

# Positions (positions table only allows NM/RM/LM/WM/AU/RT — no TA)
POS_FA_NM      = "07000007-0101-0000-0000-000000000001"
POS_FA_ASST_NM = "07000007-0101-0000-0000-000000000002"
POS_RA_RM      = "07000007-0102-0000-0000-000000000001"
POS_RA_ASST_RM = "07000007-0102-0000-0000-000000000002"
POS_SRA_RM     = "07000007-0103-0000-0000-000000000001"
POS_SRA_ASST   = "07000007-0103-0000-0000-000000000002"
POS_WHA1_WM    = "07000007-0104-0000-0000-000000000001"
POS_WHA1_ASST  = "07000007-0104-0000-0000-000000000002"
POS_WHA2_WM    = "07000007-0104-0000-0000-000000000003"
POS_WHA2_ASST  = "07000007-0104-0000-0000-000000000004"
POS_WHA3_WM    = "07000007-0104-0000-0000-000000000005"
POS_WHA3_ASST  = "07000007-0104-0000-0000-000000000006"
POS_FB_NM      = "07000007-0105-0000-0000-000000000001"
POS_FB_ASST_NM = "07000007-0105-0000-0000-000000000002"
POS_RB1_RM     = "07000007-0106-0000-0000-000000000001"
POS_RB1_ASST   = "07000007-0106-0000-0000-000000000002"
POS_SRB1_RM    = "07000007-0107-0000-0000-000000000001"
POS_SRB1_ASST  = "07000007-0107-0000-0000-000000000002"
POS_WHB11_WM   = "07000007-0108-0000-0000-000000000001"
POS_WHB11_ASST = "07000007-0108-0000-0000-000000000002"
POS_WHB12_WM   = "07000007-0108-0000-0000-000000000003"
POS_WHB12_ASST = "07000007-0108-0000-0000-000000000004"
POS_RB2_RM     = "07000007-0109-0000-0000-000000000001"
POS_RB2_ASST   = "07000007-0109-0000-0000-000000000002"
POS_WHB21_WM   = "07000007-010a-0000-0000-000000000001"
POS_WHB21_ASST = "07000007-010a-0000-0000-000000000002"
POS_WHB22_WM   = "07000007-010a-0000-0000-000000000003"
POS_WHB22_ASST = "07000007-010a-0000-0000-000000000004"
# AU and LM — tenant-wide roles assigned to Factory A node (node required by schema)
POS_AU         = "07000007-010b-0000-0000-000000000001"
POS_LM         = "07000007-010b-0000-0000-000000000002"

# Users (fixed IDs for reproducibility)
USR_TA         = "07000007-0201-0000-0000-000000000001"
USR_FA_NM      = "07000007-0202-0000-0000-000000000001"
USR_FA_ASST_NM = "07000007-0202-0000-0000-000000000002"
USR_RA_RM      = "07000007-0203-0000-0000-000000000001"
USR_RA_ASST_RM = "07000007-0203-0000-0000-000000000002"
USR_SRA_RM     = "07000007-0204-0000-0000-000000000001"
USR_SRA_ASST   = "07000007-0204-0000-0000-000000000002"
USR_WHA1_WM    = "07000007-0205-0000-0000-000000000001"
USR_WHA1_ASST  = "07000007-0205-0000-0000-000000000002"
USR_WHA2_WM    = "07000007-0205-0000-0000-000000000003"
USR_WHA2_ASST  = "07000007-0205-0000-0000-000000000004"
USR_WHA3_WM    = "07000007-0205-0000-0000-000000000005"
USR_WHA3_ASST  = "07000007-0205-0000-0000-000000000006"
USR_FB_NM      = "07000007-0206-0000-0000-000000000001"
USR_FB_ASST_NM = "07000007-0206-0000-0000-000000000002"
USR_RB1_RM     = "07000007-0207-0000-0000-000000000001"
USR_RB1_ASST   = "07000007-0207-0000-0000-000000000002"
USR_SRB1_RM    = "07000007-0208-0000-0000-000000000001"
USR_SRB1_ASST  = "07000007-0208-0000-0000-000000000002"
USR_WHB11_WM   = "07000007-0209-0000-0000-000000000001"
USR_WHB11_ASST = "07000007-0209-0000-0000-000000000002"
USR_WHB12_WM   = "07000007-0209-0000-0000-000000000003"
USR_WHB12_ASST = "07000007-0209-0000-0000-000000000004"
USR_RB2_RM     = "07000007-020a-0000-0000-000000000001"
USR_RB2_ASST   = "07000007-020a-0000-0000-000000000002"
USR_WHB21_WM   = "07000007-020b-0000-0000-000000000001"
USR_WHB21_ASST = "07000007-020b-0000-0000-000000000002"
USR_WHB22_WM   = "07000007-020b-0000-0000-000000000003"
USR_WHB22_ASST = "07000007-020b-0000-0000-000000000004"
USR_AU         = "07000007-020c-0000-0000-000000000001"
USR_LM         = "07000007-020c-0000-0000-000000000002"

# Products
CAT_RAW_MAT    = "07000007-0301-0000-0000-000000000001"
CAT_FINISHED   = "07000007-0301-0000-0000-000000000002"
TC_RAW         = "412837ec-f7ea-489b-8931-cc23fce37569"  # RAW — Raw Materials
TC_FIN         = "aa965bf5-878f-4113-8193-6719e0d61023"  # FIN — Finished Goods
TC_PKG         = "ed9779f1-de46-4a07-9e1e-fab11bd6da18"  # PKG — Packaging
PROD_P1        = "07000007-0302-0000-0000-000000000001"  # Steel Rod A
PROD_P2        = "07000007-0302-0000-0000-000000000002"  # Copper Wire B
PROD_P3        = "07000007-0302-0000-0000-000000000003"  # Product Alpha
PROD_P4        = "07000007-0302-0000-0000-000000000004"  # Secure Item X (controlled)
PROD_P5        = "07000007-0302-0000-0000-000000000005"  # Secure Item Y (controlled)

# Password hash (Test@2026)
PW_HASH = bcrypt.hashpw(b"Test@2026", bcrypt.gensalt(rounds=12)).decode("utf-8")

TODAY = date.today()


def uid() -> str:
    return str(uuid.uuid4())


def abort(part: str, err: Exception) -> None:
    print(f"\n[FATAL] {part} failed: {err}", file=sys.stderr)
    raise SystemExit(1)


# --RLS context helper ─────────────────────────────────────────────────────────
async def set_rls(s, tenant_id: str, user_id: str = SA_USER) -> None:
    await s.execute(
        text(
            "SELECT set_config('app.current_tenant_id', :tid, true),"
            "       set_config('app.current_user_id',   :uid, true)"
        ),
        {"tid": tenant_id, "uid": user_id},
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
async def main() -> None:
    async with Session() as s:

        # --PART 1 — TENANT ───────────────────────────────────────────────────
        print("\n[PART 1] Creating tenant …")
        try:
            await s.execute(
                text("""
                    INSERT INTO tenants
                        (id, name, slug, organisation_type, plan_id,
                         feature_flags, approval_thresholds,
                         default_locale, onboarding_complete,
                         sku_cap, sku_prefix, sku_counter, is_active)
                    VALUES
                        (:id, :name, :slug, 'PRODUCER', :plan_id,
                         CAST(:flags AS jsonb), CAST(:thresholds AS jsonb),
                         'en', true,
                         500, 'T07', 0, true)
                    ON CONFLICT (id) DO UPDATE SET
                        name              = EXCLUDED.name,
                        slug              = EXCLUDED.slug,
                        onboarding_complete = EXCLUDED.onboarding_complete
                """),
                {
                    "id":         T07_ID,
                    "name":       "Test Organization Seven",
                    "slug":       "tenant-07",
                    "plan_id":    PLAN_ID,
                    "flags":      json.dumps({
                        "LOGISTICS": False,
                        "AI_ANALYTICS": False,
                        "ADVANCED_BATCH_TRACKING": True,
                        "FLEET_MANAGEMENT": False,
                    }),
                    "thresholds": json.dumps({
                        "inventory:adjust": {"low": 100, "medium": 500}
                    }),
                },
            )
            await s.commit()
            print(f"  [OK]Tenant created: {T07_ID}")
        except Exception as e:
            abort("PART 1", e)

        # Set RLS for all subsequent queries
        await set_rls(s, T07_ID)

        # --PART 2 — HIERARCHY CONFIG ─────────────────────────────────────────
        print("\n[PART 2] Creating hierarchy config …")
        try:
            levels = [
                (1, "Main Factory",   "NM", False),
                (2, "Regional Center","RM", False),
                (3, "Sub Region",     "RM", False),
                (4, "Warehouse Area", "WM", True),
            ]
            for level_number, level_name, role_code, is_stock in levels:
                await s.execute(
                    text("""
                        INSERT INTO tenant_hierarchy_config
                            (tenant_id, level_number, level_name, default_role_code,
                             is_stock_holding, is_active)
                        VALUES
                            (:tid, :ln, :lname, :role, :stock, true)
                        ON CONFLICT (tenant_id, level_number) DO UPDATE SET
                            level_name       = EXCLUDED.level_name,
                            default_role_code = EXCLUDED.default_role_code,
                            is_stock_holding = EXCLUDED.is_stock_holding
                    """),
                    {
                        "tid":   T07_ID,
                        "ln":    level_number,
                        "lname": level_name,
                        "role":  role_code,
                        "stock": is_stock,
                    },
                )
            await s.commit()
            print(f"  [OK]4 hierarchy levels configured")
        except Exception as e:
            abort("PART 2", e)

        await set_rls(s, T07_ID)

        # --PART 3 — ORG NODES ────────────────────────────────────────────────
        print("\n[PART 3] Creating org nodes …")
        try:
            # (id, name, code, level, parent, is_stock_holding)
            nodes = [
                # Factory A branch
                (NODE_FA,    "Factory A",    "FA",     1, None,     False),
                (NODE_RA,    "Region A",     "RA",     2, NODE_FA,  False),
                (NODE_SRA,   "Subregion A",  "SRA",    3, NODE_RA,  False),
                (NODE_WHA1,  "WHA1",         "WHA1",   4, NODE_SRA, True),
                (NODE_WHA2,  "WHA2",         "WHA2",   4, NODE_SRA, True),
                (NODE_WHA3,  "WHA3",         "WHA3",   4, NODE_SRA, True),
                # Factory B branch
                (NODE_FB,    "Factory B",    "FB",     1, None,     False),
                (NODE_RB1,   "Region B1",    "RB1",    2, NODE_FB,  False),
                (NODE_SRB1,  "Subregion B1", "SRB1",   3, NODE_RB1, False),
                (NODE_WHB11, "WHB1-1",       "WHB1-1", 4, NODE_SRB1,True),
                (NODE_WHB12, "WHB1-2",       "WHB1-2", 4, NODE_SRB1,True),
                # Region B2 — no L3 layer (WHBs are direct children of Region B2)
                (NODE_RB2,   "Region B2",    "RB2",    2, NODE_FB,  False),
                (NODE_WHB21, "WHB2-1",       "WHB2-1", 4, NODE_RB2, True),
                (NODE_WHB22, "WHB2-2",       "WHB2-2", 4, NODE_RB2, True),
            ]
            for nid, name, code, level, parent, stock in nodes:
                await s.execute(
                    text("""
                        INSERT INTO organization_node
                            (id, tenant_id, name, code, hierarchy_level,
                             parent_node_id, is_stock_holding, is_active)
                        VALUES
                            (:id, :tid, :name, :code, :level,
                             :parent, :stock, true)
                        ON CONFLICT (id) DO UPDATE SET
                            name             = EXCLUDED.name,
                            is_stock_holding = EXCLUDED.is_stock_holding
                    """),
                    {
                        "id":     nid,
                        "tid":    T07_ID,
                        "name":   name,
                        "code":   code,
                        "level":  level,
                        "parent": parent,
                        "stock":  stock,
                    },
                )
            await s.commit()
            print(f"  [OK]{len(nodes)} org nodes created")
        except Exception as e:
            abort("PART 3", e)

        await set_rls(s, T07_ID)

        # --PART 4 — POSITIONS ────────────────────────────────────────────────
        # Schema constraint: role_code IN ('NM','RM','LM','WM','AU','RT') — no TA
        # TA uses system_role='TA' on the users table (no position row).
        # AU and LM are tenant-wide; assigned to Factory A (L1) as anchor node.
        print("\n[PART 4] Creating positions …")
        try:
            # (id, node_id, title, role_code, reports_to)
            positions = [
                # Factory A (L1, NM)
                (POS_FA_NM,      NODE_FA,    "Factory A NM",      "NM", None),
                (POS_FA_ASST_NM, NODE_FA,    "Factory A Asst NM", "NM", POS_FA_NM),
                # Region A (L2, RM)
                (POS_RA_RM,      NODE_RA,    "Region A RM",       "RM", POS_FA_NM),
                (POS_RA_ASST_RM, NODE_RA,    "Region A Asst RM",  "RM", POS_RA_RM),
                # Subregion A (L3, RM)
                (POS_SRA_RM,     NODE_SRA,   "Subregion A RM",    "RM", POS_RA_RM),
                (POS_SRA_ASST,   NODE_SRA,   "Subregion A Asst RM","RM",POS_SRA_RM),
                # WHA1 (L4, WM)
                (POS_WHA1_WM,    NODE_WHA1,  "WHA1 WM",           "WM", POS_SRA_RM),
                (POS_WHA1_ASST,  NODE_WHA1,  "WHA1 Asst WM",      "WM", POS_WHA1_WM),
                # WHA2 (L4, WM)
                (POS_WHA2_WM,    NODE_WHA2,  "WHA2 WM",           "WM", POS_SRA_RM),
                (POS_WHA2_ASST,  NODE_WHA2,  "WHA2 Asst WM",      "WM", POS_WHA2_WM),
                # WHA3 (L4, WM)
                (POS_WHA3_WM,    NODE_WHA3,  "WHA3 WM",           "WM", POS_SRA_RM),
                (POS_WHA3_ASST,  NODE_WHA3,  "WHA3 Asst WM",      "WM", POS_WHA3_WM),
                # Factory B (L1, NM)
                (POS_FB_NM,      NODE_FB,    "Factory B NM",      "NM", None),
                (POS_FB_ASST_NM, NODE_FB,    "Factory B Asst NM", "NM", POS_FB_NM),
                # Region B1 (L2, RM)
                (POS_RB1_RM,     NODE_RB1,   "Region B1 RM",      "RM", POS_FB_NM),
                (POS_RB1_ASST,   NODE_RB1,   "Region B1 Asst RM", "RM", POS_RB1_RM),
                # Subregion B1 (L3, RM)
                (POS_SRB1_RM,    NODE_SRB1,  "Subregion B1 RM",   "RM", POS_RB1_RM),
                (POS_SRB1_ASST,  NODE_SRB1,  "Subregion B1 Asst RM","RM",POS_SRB1_RM),
                # WHB1-1 (L4, WM)
                (POS_WHB11_WM,   NODE_WHB11, "WHB1-1 WM",         "WM", POS_SRB1_RM),
                (POS_WHB11_ASST, NODE_WHB11, "WHB1-1 Asst WM",    "WM", POS_WHB11_WM),
                # WHB1-2 (L4, WM)
                (POS_WHB12_WM,   NODE_WHB12, "WHB1-2 WM",         "WM", POS_SRB1_RM),
                (POS_WHB12_ASST, NODE_WHB12, "WHB1-2 Asst WM",    "WM", POS_WHB12_WM),
                # Region B2 (L2, RM)
                (POS_RB2_RM,     NODE_RB2,   "Region B2 RM",      "RM", POS_FB_NM),
                (POS_RB2_ASST,   NODE_RB2,   "Region B2 Asst RM", "RM", POS_RB2_RM),
                # WHB2-1 (L4, WM — direct child of Region B2, no L3)
                (POS_WHB21_WM,   NODE_WHB21, "WHB2-1 WM",         "WM", POS_RB2_RM),
                (POS_WHB21_ASST, NODE_WHB21, "WHB2-1 Asst WM",    "WM", POS_WHB21_WM),
                # WHB2-2 (L4, WM)
                (POS_WHB22_WM,   NODE_WHB22, "WHB2-2 WM",         "WM", POS_RB2_RM),
                (POS_WHB22_ASST, NODE_WHB22, "WHB2-2 Asst WM",    "WM", POS_WHB22_WM),
                # Tenant-wide roles anchored at Factory A (L1) — schema requires node_id
                (POS_AU,         NODE_FA,    "T07 AU",            "AU", None),
                (POS_LM,         NODE_FA,    "T07 LM",            "LM", None),
            ]
            for pid, nid, title, role_code, reports_to in positions:
                await s.execute(
                    text("""
                        INSERT INTO positions
                            (id, tenant_id, node_id, title, role_code,
                             reports_to_position_id, is_active)
                        VALUES
                            (:id, :tid, :nid, :title, :role, :rpts, true)
                        ON CONFLICT (id) DO UPDATE SET
                            title    = EXCLUDED.title,
                            role_code = EXCLUDED.role_code
                    """),
                    {
                        "id":    pid,
                        "tid":   T07_ID,
                        "nid":   nid,
                        "title": title,
                        "role":  role_code,
                        "rpts":  reports_to,
                    },
                )
            await s.commit()
            print(f"  [OK]{len(positions)} positions created")
        except Exception as e:
            abort("PART 4", e)

        await set_rls(s, T07_ID)

        # --PART 5 — USERS ────────────────────────────────────────────────────
        # After migration 031: role + warehouse_id dropped from users table.
        # TA users: system_role='TA', no position assignment.
        # All others: system_role=NULL, assigned via personnel_positions (PRIMARY).
        print("\n[PART 5] Creating users …")
        try:
            # (usr_id, email, full_name, system_role, position_id)
            users = [
                # TA — no position (system_role drives JWT)
                (USR_TA,         "admin@t07.com",             "T07 Admin",             "TA",  None),
                # Factory A
                (USR_FA_NM,      "nm_factorya@t07.com",       "A-Factory NM",          None,  POS_FA_NM),
                (USR_FA_ASST_NM, "asst_nm_factorya@t07.com",  "A-Factory Asst NM",     None,  POS_FA_ASST_NM),
                (USR_RA_RM,      "rm_regiona@t07.com",        "A-Region RM",           None,  POS_RA_RM),
                (USR_RA_ASST_RM, "asst_rm_regiona@t07.com",   "A-Region Asst RM",      None,  POS_RA_ASST_RM),
                (USR_SRA_RM,     "rm_subregiona@t07.com",     "A-SubRegion RM",        None,  POS_SRA_RM),
                (USR_SRA_ASST,   "asst_rm_subregiona@t07.com","A-SubRegion Asst RM",   None,  POS_SRA_ASST),
                (USR_WHA1_WM,    "wm_wha1@t07.com",           "A-WHA1 WM",             None,  POS_WHA1_WM),
                (USR_WHA1_ASST,  "asst_wm_wha1@t07.com",      "A-WHA1 Asst WM",        None,  POS_WHA1_ASST),
                (USR_WHA2_WM,    "wm_wha2@t07.com",           "A-WHA2 WM",             None,  POS_WHA2_WM),
                (USR_WHA2_ASST,  "asst_wm_wha2@t07.com",      "A-WHA2 Asst WM",        None,  POS_WHA2_ASST),
                (USR_WHA3_WM,    "wm_wha3@t07.com",           "A-WHA3 WM",             None,  POS_WHA3_WM),
                (USR_WHA3_ASST,  "asst_wm_wha3@t07.com",      "A-WHA3 Asst WM",        None,  POS_WHA3_ASST),
                # Factory B
                (USR_FB_NM,      "nm_factoryb@t07.com",       "B-Factory NM",          None,  POS_FB_NM),
                (USR_FB_ASST_NM, "asst_nm_factoryb@t07.com",  "B-Factory Asst NM",     None,  POS_FB_ASST_NM),
                (USR_RB1_RM,     "rm_regionb1@t07.com",       "B-Region B1 RM",        None,  POS_RB1_RM),
                (USR_RB1_ASST,   "asst_rm_regionb1@t07.com",  "B-Region B1 Asst RM",   None,  POS_RB1_ASST),
                (USR_SRB1_RM,    "rm_subregionb1@t07.com",    "B-SubRegion B1 RM",     None,  POS_SRB1_RM),
                (USR_SRB1_ASST,  "asst_rm_subregionb1@t07.com","B-SubRegion B1 Asst RM",None, POS_SRB1_ASST),
                (USR_WHB11_WM,   "wm_whb1_1@t07.com",         "B-WHB1-1 WM",           None,  POS_WHB11_WM),
                (USR_WHB11_ASST, "asst_wm_whb1_1@t07.com",    "B-WHB1-1 Asst WM",      None,  POS_WHB11_ASST),
                (USR_WHB12_WM,   "wm_whb1_2@t07.com",         "B-WHB1-2 WM",           None,  POS_WHB12_WM),
                (USR_WHB12_ASST, "asst_wm_whb1_2@t07.com",    "B-WHB1-2 Asst WM",      None,  POS_WHB12_ASST),
                (USR_RB2_RM,     "rm_regionb2@t07.com",       "B-Region B2 RM",        None,  POS_RB2_RM),
                (USR_RB2_ASST,   "asst_rm_regionb2@t07.com",  "B-Region B2 Asst RM",   None,  POS_RB2_ASST),
                (USR_WHB21_WM,   "wm_whb2_1@t07.com",         "B-WHB2-1 WM",           None,  POS_WHB21_WM),
                (USR_WHB21_ASST, "asst_wm_whb2_1@t07.com",    "B-WHB2-1 Asst WM",      None,  POS_WHB21_ASST),
                (USR_WHB22_WM,   "wm_whb2_2@t07.com",         "B-WHB2-2 WM",           None,  POS_WHB22_WM),
                (USR_WHB22_ASST, "asst_wm_whb2_2@t07.com",    "B-WHB2-2 Asst WM",      None,  POS_WHB22_ASST),
                # Tenant-wide
                (USR_AU,         "au@t07.com",                "T07 Auditor",           None,  POS_AU),
                (USR_LM,         "lm@t07.com",                "T07 Logistics",         None,  POS_LM),
            ]

            for uid_val, email, full_name, sys_role, pos_id in users:
                cognito_sub = email.replace("@", "_").replace(".", "_")
                await s.execute(
                    text("""
                        INSERT INTO users
                            (id, tenant_id, cognito_sub, email, full_name,
                             locale, is_active, password_hash, must_reset_password,
                             system_role, created_by)
                        VALUES
                            (:id, :tid, :sub, :email, :name,
                             'en', true, :pw, false,
                             :sysrole, :created_by)
                        ON CONFLICT (id) DO UPDATE SET
                            email         = EXCLUDED.email,
                            full_name     = EXCLUDED.full_name,
                            password_hash = EXCLUDED.password_hash,
                            system_role   = EXCLUDED.system_role
                    """),
                    {
                        "id":         uid_val,
                        "tid":        T07_ID,
                        "sub":        cognito_sub,
                        "email":      email,
                        "name":       full_name,
                        "pw":         PW_HASH,
                        "sysrole":    sys_role,
                        "created_by": SA_USER,
                    },
                )
                # Personnel position assignment for non-TA users
                if pos_id is not None:
                    pp_id = uid()
                    await s.execute(
                        text("""
                            INSERT INTO personnel_positions
                                (id, tenant_id, user_id, position_id,
                                 assignment_type, valid_from, is_active, assigned_by)
                            VALUES
                                (:id, :tid, :uid, :pid,
                                 'PRIMARY', CURRENT_DATE, true, :assigned_by)
                            ON CONFLICT (user_id)
                            WHERE assignment_type = 'PRIMARY' AND is_active = true
                            DO NOTHING
                        """),
                        {
                            "id":          pp_id,
                            "tid":         T07_ID,
                            "uid":         uid_val,
                            "pid":         pos_id,
                            "assigned_by": SA_USER,
                        },
                    )
            await s.commit()
            print(f"  [OK]{len(users)} users created with personnel_positions")
        except Exception as e:
            abort("PART 5", e)

        await set_rls(s, T07_ID)

        # --PART 6 — PRODUCTS ─────────────────────────────────────────────────
        print("\n[PART 6] Creating products …")
        try:
            # Categories
            for cat_id, cat_name in [
                (CAT_RAW_MAT,  "Raw Materials"),
                (CAT_FINISHED, "Finished Goods"),
            ]:
                await s.execute(
                    text("""
                        INSERT INTO product_categories (id, tenant_id, name, is_active)
                        VALUES (:id, :tid, :name, true)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                    """),
                    {"id": cat_id, "tid": T07_ID, "name": cat_name},
                )

            # Type codes — realistic codes used by products and test suite
            for tc_id, tc_code, tc_desc in [
                (TC_RAW, "RAW", "Raw Materials"),
                (TC_FIN, "FIN", "Finished Goods"),
                (TC_PKG, "PKG", "Packaging"),
            ]:
                await s.execute(
                    text("""
                        INSERT INTO product_type_codes (id, tenant_id, code, description, is_active)
                        VALUES (:id, :tid, :code, :desc, true)
                        ON CONFLICT (id) DO UPDATE SET
                            code        = EXCLUDED.code,
                            description = EXCLUDED.description
                    """),
                    {"id": tc_id, "tid": T07_ID, "code": tc_code, "desc": tc_desc},
                )

            # Products: (id, sku, name, uom, cat_id, tc_id)
            products = [
                (PROD_P1, "T07-RM-001", "Steel Rod A",    "KG",    CAT_RAW_MAT,  TC_RAW),
                (PROD_P2, "T07-RM-002", "Copper Wire B",  "Roll",  CAT_RAW_MAT,  TC_RAW),
                (PROD_P3, "T07-FG-001", "Product Alpha",  "Unit",  CAT_FINISHED, TC_FIN),
                (PROD_P4, "T07-FG-002", "Secure Item X",  "Unit",  CAT_FINISHED, TC_FIN),
                (PROD_P5, "T07-FG-003", "Secure Item Y",  "Piece", CAT_FINISHED, TC_PKG),
            ]
            for p_id, sku, name, uom, cat_id, tc_id in products:
                await s.execute(
                    text("""
                        INSERT INTO products
                            (id, tenant_id, sku, name, unit_of_measure,
                             category_id, type_code_id, batch_tracking, expiry_tracking,
                             is_active, created_by)
                        VALUES
                            (:id, :tid, :sku, :name, :uom,
                             :cat, :tc, false, false,
                             true, :created_by)
                        ON CONFLICT (id) DO UPDATE SET
                            name         = EXCLUDED.name,
                            sku          = EXCLUDED.sku,
                            type_code_id = EXCLUDED.type_code_id
                    """),
                    {
                        "id":         p_id,
                        "tid":        T07_ID,
                        "sku":        sku,
                        "name":       name,
                        "uom":        uom,
                        "cat":        cat_id,
                        "tc":         tc_id,
                        "created_by": USR_TA,
                    },
                )
            await s.commit()
            print(f"  [OK] 2 categories + 3 type codes + {len(products)} products created")

            # Product approval overrides for controlled items (product_approval_minimums)
            # P4 — Secure Item X
            #   PULL:       ALWAYS  → Factory A NM must approve
            #   PUSH:       ALWAYS  → Factory A NM must approve
            #   ADJUSTMENT: QUANTITY threshold=50 → Factory A NM must approve
            #
            # P5 — Secure Item Y
            #   PULL:       QUANTITY threshold=100 → Region A RM must approve
            #   ADJUSTMENT: ALWAYS  → Region A RM must approve

            overrides = [
                # (product_id, tx_type, threshold_type, qty_threshold, approver_pos_id)
                (PROD_P4, "PULL",       "ALWAYS",    None, POS_FA_NM),
                (PROD_P4, "PUSH",       "ALWAYS",    None, POS_FA_NM),
                (PROD_P4, "ADJUSTMENT", "QUANTITY",  50,   POS_FA_NM),
                (PROD_P5, "PULL",       "QUANTITY",  100,  POS_RA_RM),
                (PROD_P5, "ADJUSTMENT", "ALWAYS",    None, POS_RA_RM),
            ]
            for p_id, tx_type, ttype, qty_thr, approver_pos in overrides:
                await s.execute(
                    text("""
                        INSERT INTO product_approval_minimums
                            (tenant_id, product_id, transaction_type,
                             threshold_type, qty_threshold,
                             approver_position_id,
                             is_active, created_by)
                        VALUES
                            (:tid, :pid, :txtype,
                             :ttype, :qty,
                             :approver,
                             true, :created_by)
                        ON CONFLICT (product_id, transaction_type) DO UPDATE SET
                            threshold_type       = EXCLUDED.threshold_type,
                            qty_threshold        = EXCLUDED.qty_threshold,
                            approver_position_id = EXCLUDED.approver_position_id,
                            is_active            = EXCLUDED.is_active
                    """),
                    {
                        "tid":         T07_ID,
                        "pid":         p_id,
                        "txtype":      tx_type,
                        "ttype":       ttype,
                        "qty":         qty_thr,
                        "approver":    approver_pos,
                        "created_by":  USR_TA,
                    },
                )
            await s.commit()
            print(f"  [OK]{len(overrides)} product approval overrides set (P4 + P5)")
        except Exception as e:
            abort("PART 6", e)

        await set_rls(s, T07_ID)

        # --PART 7 — TRANSFER TYPE CONFIG ────────────────────────────────────
        print("\n[PART 7] Creating transfer type config …")
        try:
            ttc_ids: dict[str, str] = {}  # underlying_type → ttc_id
            type_configs = [
                ("PULL",   "Request Stock",  "L1–L4 can initiate PULL requests",     1),
                ("PUSH",   "Send Stock",     "L1–L2 can proactively push stock",      2),
                ("SISTER", "Branch Exchange","L4 warehouse-to-warehouse peer exchange",3),
            ]
            for utype, dname, desc, sort in type_configs:
                ttc_id = uid()
                # Check for existing row (idempotent)
                row = (await s.execute(
                    text("SELECT id FROM transfer_type_config "
                         "WHERE tenant_id=:tid AND underlying_type=:utype"),
                    {"tid": T07_ID, "utype": utype},
                )).fetchone()
                if row:
                    ttc_ids[utype] = str(row[0])
                    await s.execute(
                        text("""
                            UPDATE transfer_type_config
                            SET display_name=:dname, description=:desc, is_active=true
                            WHERE id=:id
                        """),
                        {"id": ttc_ids[utype], "dname": dname, "desc": desc},
                    )
                else:
                    ttc_ids[utype] = ttc_id
                    await s.execute(
                        text("""
                            INSERT INTO transfer_type_config
                                (id, tenant_id, underlying_type, display_name,
                                 description, is_active, sort_order)
                            VALUES
                                (:id, :tid, :utype, :dname,
                                 :desc, true, :sort)
                        """),
                        {
                            "id":    ttc_id,
                            "tid":   T07_ID,
                            "utype": utype,
                            "dname": dname,
                            "desc":  desc,
                            "sort":  sort,
                        },
                    )

            # Level permissions
            # PULL: levels 1–4 can initiate; all can receive
            # PUSH: levels 1–2 can initiate; all can receive
            # SISTER: level 4 only can initiate and receive
            level_perms = {
                "PULL":   [(1, True, True), (2, True, True), (3, True, True), (4, True, True)],
                "PUSH":   [(1, True, True), (2, True, True), (3, False,True), (4, False,True)],
                "SISTER": [(1, False,False),(2, False,False),(3, False,False),(4, True, True)],
            }
            for utype, perms in level_perms.items():
                ttc_id = ttc_ids[utype]
                # Delete existing level perms to re-seed cleanly
                await s.execute(
                    text("DELETE FROM transfer_type_level_permissions "
                         "WHERE transfer_type_config_id=:ttc_id"),
                    {"ttc_id": ttc_id},
                )
                for lvl, can_init, can_recv in perms:
                    await s.execute(
                        text("""
                            INSERT INTO transfer_type_level_permissions
                                (tenant_id, transfer_type_config_id, level_number,
                                 can_initiate, can_receive)
                            VALUES
                                (:tid, :ttc_id, :lvl, :init, :recv)
                        """),
                        {
                            "tid":    T07_ID,
                            "ttc_id": ttc_id,
                            "lvl":    lvl,
                            "init":   can_init,
                            "recv":   can_recv,
                        },
                    )
            await s.commit()
            print(f"  [OK]3 transfer type configs + 12 level permissions set")
            print(f"    PULL_CFG_ID   = {ttc_ids['PULL']}")
            print(f"    PUSH_CFG_ID   = {ttc_ids['PUSH']}")
            print(f"    SISTER_CFG_ID = {ttc_ids['SISTER']}")
        except Exception as e:
            abort("PART 7", e)

        await set_rls(s, T07_ID)

        # --PART 8 — APPROVAL RULES ───────────────────────────────────────────
        print("\n[PART 8] Creating approval rules …")
        try:
            # --8a Self-approval policies (transfers) ─────────────────────────
            # Controls the max qty a role can self-approve without escalating
            # unique: (tenant_id, role_code, level_number)
            sap_rows = [
                ("NM", 1, 50000),
                ("RM", 2, 20000),
                ("RM", 3, 10000),
                ("WM", 4,  5000),
            ]
            for role_code, level_num, qty_limit in sap_rows:
                await s.execute(
                    text("""
                        INSERT INTO self_approval_policies
                            (tenant_id, role_code, level_number,
                             transfer_types, threshold_type, qty_limit,
                             is_active)
                        VALUES
                            (:tid, :role, :lvl,
                             ARRAY['PULL','PUSH','SISTER']::VARCHAR(20)[],
                             'QUANTITY', :qty, true)
                        ON CONFLICT (tenant_id, role_code, level_number) DO UPDATE SET
                            qty_limit     = EXCLUDED.qty_limit,
                            is_active     = EXCLUDED.is_active,
                            transfer_types = EXCLUDED.transfer_types
                    """),
                    {"tid": T07_ID, "role": role_code, "lvl": level_num, "qty": qty_limit},
                )

            # --8a-adj ADJUSTMENT self-approval policies ─────────────────────
            # Separate ADJUSTMENT-specific limits (tighter than PULL/PUSH/SISTER).
            # Delete ADJUSTMENT-only rows first so this block is fully idempotent.
            await s.execute(
                text("""
                    DELETE FROM self_approval_policies
                    WHERE tenant_id = :tid
                      AND transfer_types = ARRAY['ADJUSTMENT']::VARCHAR(20)[]
                """),
                {"tid": T07_ID},
            )
            adj_sap_data = [
                # (role_code, level_number, qty_limit)  — None = unlimited
                ("NM", 1, None),
                ("RM", 2, 10000),
                ("RM", 3,  5000),
                ("WM", 4,  1000),
            ]
            for role_code, level_num, qty_limit in adj_sap_data:
                await s.execute(
                    text("""
                        INSERT INTO self_approval_policies
                            (tenant_id, role_code, level_number,
                             transfer_types, threshold_type, qty_limit,
                             is_active)
                        VALUES
                            (:tid, :role, :lvl,
                             ARRAY['ADJUSTMENT']::VARCHAR(20)[],
                             'QUANTITY', :qty, true)
                    """),
                    {
                        "tid":  T07_ID,
                        "role": role_code,
                        "lvl":  level_num,
                        "qty":  qty_limit,
                    },
                )

            # --8b Adjustment self-approval (adjustment_approval_rules) ───────
            # mode=GLOBAL means it applies to any reason_code
            # idx_adj_approval_unique is an expression index — delete-first is simpler
            await s.execute(
                text("DELETE FROM adjustment_approval_rules WHERE tenant_id=:tid"),
                {"tid": T07_ID},
            )
            adj_sap_rows = [
                # (role_code, level_number, qty_limit)  — qty_limit=None means no limit
                ("NM", 1, None),
                ("RM", 2, 10000),
                ("RM", 3,  5000),
                ("WM", 4,  1000),
            ]
            for role_code, level_num, qty_limit in adj_sap_rows:
                await s.execute(
                    text("""
                        INSERT INTO adjustment_approval_rules
                            (tenant_id, role_code, level_number,
                             mode, threshold_type, qty_limit,
                             priority, is_active)
                        VALUES
                            (:tid, :role, :lvl,
                             'GLOBAL', 'QUANTITY', :qty,
                             10, true)
                    """),
                    {
                        "tid":  T07_ID,
                        "role": role_code,
                        "lvl":  level_num,
                        "qty":  qty_limit,
                    },
                )

            # --8c Transfer approval routing rules ────────────────────────────
            # approval_steps format:
            #   [{"sequence": N, "position_title": "...", "resolution": "...",
            #     "execution_mode": "SEQUENTIAL", "sla_hours": N}]
            #
            # resolution values observed in existing tests:
            #   "source_parent_node"      — approver comes from source's parent node
            #   "destination_parent_node" — approver comes from destination's parent node
            #   "named_position"          — specific position by title at a named node
            #
            # Clear existing rules for idempotency
            pull_id   = ttc_ids["PULL"]
            push_id   = ttc_ids["PUSH"]
            sister_id = ttc_ids["SISTER"]

            for ttc_id in [pull_id, push_id, sister_id]:
                await s.execute(
                    text("DELETE FROM transfer_approval_rules WHERE transfer_type_config_id=:ttc"),
                    {"ttc": ttc_id},
                )

            # PULL rules
            pull_rules = [
                # Rule 1: L1→Any, no steps (NM self-approves via policy)
                {
                    "ttc_id": pull_id, "src": 1, "dst": None,
                    "qty_min": 0, "qty_max": None, "priority": 1,
                    "steps": [],
                },
                # Rule 2: L2→L1, Factory A NM approves, 48h
                {
                    "ttc_id": pull_id, "src": 2, "dst": 1,
                    "qty_min": 0, "qty_max": None, "priority": 2,
                    "steps": [{"sequence": 1, "position_title": "Factory A NM",
                               "resolution": "source_parent_node",
                               "execution_mode": "SEQUENTIAL", "sla_hours": 48}],
                },
                # Rule 3: L3→L2, Region A RM approves, 24h
                {
                    "ttc_id": pull_id, "src": 3, "dst": 2,
                    "qty_min": 0, "qty_max": None, "priority": 3,
                    "steps": [{"sequence": 1, "position_title": "Region A RM",
                               "resolution": "source_parent_node",
                               "execution_mode": "SEQUENTIAL", "sla_hours": 24}],
                },
                # Rule 4: L4→L3, 0–5000, Subregion A RM approves, 24h
                {
                    "ttc_id": pull_id, "src": 4, "dst": 3,
                    "qty_min": 0, "qty_max": 5000, "priority": 4,
                    "steps": [{"sequence": 1, "position_title": "Subregion A RM",
                               "resolution": "source_parent_node",
                               "execution_mode": "SEQUENTIAL", "sla_hours": 24}],
                },
                # Rule 5: L4→L3, 5001+, Subregion A RM then Region A RM, 24h each
                {
                    "ttc_id": pull_id, "src": 4, "dst": 3,
                    "qty_min": 5001, "qty_max": None, "priority": 5,
                    "steps": [
                        {"sequence": 1, "position_title": "Subregion A RM",
                         "resolution": "source_parent_node",
                         "execution_mode": "SEQUENTIAL", "sla_hours": 24},
                        {"sequence": 2, "position_title": "Region A RM",
                         "resolution": "source_parent_node",
                         "execution_mode": "SEQUENTIAL", "sla_hours": 24},
                    ],
                },
            ]

            # PUSH rules
            push_rules = [
                # Rule 1: L1→Any, Factory A NM advises, 48h
                {
                    "ttc_id": push_id, "src": 1, "dst": None,
                    "qty_min": 0, "qty_max": None, "priority": 1,
                    "steps": [{"sequence": 1, "position_title": "Factory A NM",
                               "resolution": "source_parent_node",
                               "execution_mode": "SEQUENTIAL", "sla_hours": 48}],
                },
                # Rule 2: L2→L4, Region A RM approves, 24h
                {
                    "ttc_id": push_id, "src": 2, "dst": 4,
                    "qty_min": 0, "qty_max": None, "priority": 2,
                    "steps": [{"sequence": 1, "position_title": "Region A RM",
                               "resolution": "source_parent_node",
                               "execution_mode": "SEQUENTIAL", "sla_hours": 24}],
                },
            ]

            # SISTER rules
            sister_rules = [
                # Rule 1: L4→L4, 0–1000, no approval steps (peer self-approves)
                {
                    "ttc_id": sister_id, "src": 4, "dst": 4,
                    "qty_min": 0, "qty_max": 1000, "priority": 1,
                    "steps": [],
                },
                # Rule 2: L4→L4, 1001+, Subregion A RM approves, 24h
                {
                    "ttc_id": sister_id, "src": 4, "dst": 4,
                    "qty_min": 1001, "qty_max": None, "priority": 2,
                    "steps": [{"sequence": 1, "position_title": "Subregion A RM",
                               "resolution": "source_parent_node",
                               "execution_mode": "SEQUENTIAL", "sla_hours": 24}],
                },
            ]

            all_rules = pull_rules + push_rules + sister_rules
            for rule in all_rules:
                steps_json = json.dumps(rule["steps"])
                await s.execute(
                    text("""
                        INSERT INTO transfer_approval_rules
                            (tenant_id, transfer_type_config_id,
                             source_level, destination_level,
                             quantity_min, quantity_max,
                             value_min, value_max,
                             threshold_type, currency,
                             approval_steps, priority, is_active)
                        VALUES
                            (:tid, :ttc_id,
                             :src, :dst,
                             :qty_min, :qty_max,
                             0, NULL,
                             'QUANTITY', 'ETB',
                             CAST(:steps AS jsonb), :priority, true)
                    """),
                    {
                        "tid":     T07_ID,
                        "ttc_id":  rule["ttc_id"],
                        "src":     rule["src"],
                        "dst":     rule["dst"],
                        "qty_min": rule["qty_min"],
                        "qty_max": rule["qty_max"],
                        "steps":   steps_json,
                        "priority":rule["priority"],
                    },
                )

            await s.commit()
            pull_count   = len(pull_rules)
            push_count   = len(push_rules)
            sister_count = len(sister_rules)
            print(f"  [OK]Self-approval policies: 4 PULL/PUSH/SISTER + 4 ADJUSTMENT (NM/RM-L2/RM-L3/WM)")
            print(f"  [OK]Adjustment approval rules: 4 (NM/RM-L2/RM-L3/WM)")
            print(f"  [OK]Transfer approval rules: {pull_count} PULL + {push_count} PUSH + {sister_count} SISTER")
        except Exception as e:
            abort("PART 8", e)

        await set_rls(s, T07_ID)

        # --PART 9 — OPENING STOCK ────────────────────────────────────────────
        print("\n[PART 9] Seeding opening stock …")
        try:
            # Map SKU → product_id
            sku_to_id = {
                "T07-RM-001": PROD_P1,  # Steel Rod A
                "T07-RM-002": PROD_P2,  # Copper Wire B
                "T07-FG-001": PROD_P3,  # Product Alpha
                "T07-FG-002": PROD_P4,  # Secure Item X
                "T07-FG-003": PROD_P5,  # Secure Item Y
            }
            # (node_id, {sku: qty})
            opening_stock = [
                (NODE_WHA1,  {"T07-RM-001": 500, "T07-RM-002": 200,
                              "T07-FG-001": 100, "T07-FG-002": 50,
                              "T07-FG-003": 150}),
                (NODE_WHA2,  {"T07-RM-001": 300, "T07-RM-002": 100,
                              "T07-FG-001": 75}),
                (NODE_WHA3,  {"T07-RM-001": 200, "T07-FG-001": 50,
                              "T07-FG-003": 80}),
                (NODE_WHB11, {"T07-RM-001": 400, "T07-RM-002": 150,
                              "T07-FG-001": 60}),
                (NODE_WHB12, {"T07-RM-001": 250, "T07-RM-002": 80}),
                (NODE_WHB21, {"T07-RM-001": 350, "T07-FG-001": 90,
                              "T07-FG-002": 30}),
                (NODE_WHB22, {"T07-RM-001": 180, "T07-RM-002": 60,
                              "T07-FG-003": 40}),
            ]

            tx_count = 0
            skipped  = 0
            for node_id, sku_qtys in opening_stock:
                for sku, qty in sku_qtys.items():
                    prod_id  = sku_to_id[sku]
                    ikey     = f"seed:t07:open:{sku}:{node_id}"
                    tx_id    = uid()

                    # Idempotency: skip if already seeded (ikey is stored on the row)
                    existing = (await s.execute(
                        text("SELECT 1 FROM inventory_transactions "
                             "WHERE tenant_id=:tid AND idempotency_key=:ikey LIMIT 1"),
                        {"tid": T07_ID, "ikey": ikey},
                    )).fetchone()
                    if existing:
                        skipped += 1
                        continue

                    # Ledger INSERT
                    await s.execute(
                        text("""
                            INSERT INTO inventory_transactions
                                (id, transaction_date, tenant_id, type,
                                 product_id, warehouse_id, quantity,
                                 idempotency_key, source, created_by)
                            VALUES
                                (:id, :td, :tid, 'RECEIVE',
                                 :pid, :wid, :qty,
                                 :ikey, 'SEED', :uid)
                        """),
                        {
                            "id":   tx_id,
                            "td":   TODAY,
                            "tid":  T07_ID,
                            "pid":  prod_id,
                            "wid":  node_id,
                            "qty":  qty,
                            "ikey": ikey,
                            "uid":  USR_TA,
                        },
                    )

                    # Balance update — SET (not add) so re-runs stay idempotent
                    await s.execute(
                        text("""
                            INSERT INTO inventory_balances
                                (tenant_id, product_id, warehouse_id, quantity)
                            VALUES
                                (:tid, :pid, :wid, :qty)
                            ON CONFLICT (tenant_id, product_id, warehouse_id)
                            WHERE lot_number IS NULL
                            DO UPDATE SET
                                quantity   = EXCLUDED.quantity,
                                updated_at = now()
                        """),
                        {"tid": T07_ID, "pid": prod_id, "wid": node_id, "qty": qty},
                    )
                    tx_count += 1

            await s.commit()
            if skipped:
                print(f"  [skip]{skipped} stock entries already existed — skipped")
            print(f"  [OK]{tx_count} RECEIVE transactions seeded across 7 warehouses")
        except Exception as e:
            abort("PART 9", e)

        # --SUMMARY ───────────────────────────────────────────────────────────
        await set_rls(s, T07_ID)
        counts = {}
        for tbl in ("organization_node", "positions", "users",
                    "products", "inventory_transactions"):
            row = (await s.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :tid"),
                {"tid": T07_ID},
            )).scalar()
            counts[tbl] = row

    await engine.dispose()

    # --CREDENTIALS TABLE ─────────────────────────────────────────────────────
    SEP  = "+" + "-" * 20 + "+" + "-" * 38 + "+" + "-" * 18 + "+"
    HDR  = "| {:<18} | {:<36} | {:<16} |"
    ROW  = "| {:<18} | {:<36} | {:<16} |"
    print()
    print("=" * 80)
    print("  TENANT 07 -- TEST CREDENTIALS")
    print("=" * 80)
    print(SEP)
    print(HDR.format("Role", "Email", "Password"))
    print(SEP)

    rows = [
        # TA
        ("TA",               "admin@t07.com",               "Test@2026"),
        ("-" * 18,           "-" * 36,                      "-" * 16),
        # Factory A
        ("NM  (Factory A)",  "nm_factorya@t07.com",         "Test@2026"),
        ("Asst NM (FA)",     "asst_nm_factorya@t07.com",    "Test@2026"),
        ("RM  (Region A)",   "rm_regiona@t07.com",          "Test@2026"),
        ("Asst RM (RA)",     "asst_rm_regiona@t07.com",     "Test@2026"),
        ("RM  (SubReg A)",   "rm_subregiona@t07.com",       "Test@2026"),
        ("Asst RM (SRA)",    "asst_rm_subregiona@t07.com",  "Test@2026"),
        ("WM  (WHA1)",       "wm_wha1@t07.com",             "Test@2026"),
        ("Asst WM (WHA1)",   "asst_wm_wha1@t07.com",        "Test@2026"),
        ("WM  (WHA2)",       "wm_wha2@t07.com",             "Test@2026"),
        ("Asst WM (WHA2)",   "asst_wm_wha2@t07.com",        "Test@2026"),
        ("WM  (WHA3)",       "wm_wha3@t07.com",             "Test@2026"),
        ("Asst WM (WHA3)",   "asst_wm_wha3@t07.com",        "Test@2026"),
        ("-" * 18,           "-" * 36,                      "-" * 16),
        # Factory B
        ("NM  (Factory B)",  "nm_factoryb@t07.com",         "Test@2026"),
        ("Asst NM (FB)",     "asst_nm_factoryb@t07.com",    "Test@2026"),
        ("RM  (Region B1)",  "rm_regionb1@t07.com",         "Test@2026"),
        ("Asst RM (RB1)",    "asst_rm_regionb1@t07.com",    "Test@2026"),
        ("RM  (SubReg B1)",  "rm_subregionb1@t07.com",      "Test@2026"),
        ("Asst RM (SRB1)",   "asst_rm_subregionb1@t07.com", "Test@2026"),
        ("WM  (WHB1-1)",     "wm_whb1_1@t07.com",           "Test@2026"),
        ("Asst WM B1-1",     "asst_wm_whb1_1@t07.com",      "Test@2026"),
        ("WM  (WHB1-2)",     "wm_whb1_2@t07.com",           "Test@2026"),
        ("Asst WM B1-2",     "asst_wm_whb1_2@t07.com",      "Test@2026"),
        ("RM  (Region B2)",  "rm_regionb2@t07.com",         "Test@2026"),
        ("Asst RM (RB2)",    "asst_rm_regionb2@t07.com",    "Test@2026"),
        ("WM  (WHB2-1)",     "wm_whb2_1@t07.com",           "Test@2026"),
        ("Asst WM B2-1",     "asst_wm_whb2_1@t07.com",      "Test@2026"),
        ("WM  (WHB2-2)",     "wm_whb2_2@t07.com",           "Test@2026"),
        ("Asst WM B2-2",     "asst_wm_whb2_2@t07.com",      "Test@2026"),
        ("-" * 18,           "-" * 36,                      "-" * 16),
        # Tenant-wide
        ("AU  (Auditor)",    "au@t07.com",                  "Test@2026"),
        ("LM  (Logistics)",  "lm@t07.com",                  "Test@2026"),
    ]
    for role_label, email, pw in rows:
        print(ROW.format(role_label, email, pw))

    print(SEP)

    print()
    print("--TENANT IDs ──────────────────────────────────────────────────────────")
    print(f"  Tenant 07 ID : {T07_ID}")
    print(f"  Plan ID      : {PLAN_ID}")

    print()
    print("--ORG NODE IDs ────────────────────────────────────────────────────────")
    print(f"  Factory A    : {NODE_FA}")
    print(f"  Region A     : {NODE_RA}")
    print(f"  Subregion A  : {NODE_SRA}")
    print(f"  WHA1         : {NODE_WHA1}")
    print(f"  WHA2         : {NODE_WHA2}")
    print(f"  WHA3         : {NODE_WHA3}")
    print(f"  Factory B    : {NODE_FB}")
    print(f"  Region B1    : {NODE_RB1}")
    print(f"  Subregion B1 : {NODE_SRB1}")
    print(f"  WHB1-1       : {NODE_WHB11}")
    print(f"  WHB1-2       : {NODE_WHB12}")
    print(f"  Region B2    : {NODE_RB2}")
    print(f"  WHB2-1       : {NODE_WHB21}")
    print(f"  WHB2-2       : {NODE_WHB22}")

    print()
    print("--KEY POSITION IDs ────────────────────────────────────────────────────")
    print(f"  Factory A NM     : {POS_FA_NM}")
    print(f"  Factory A Asst NM: {POS_FA_ASST_NM}")
    print(f"  Region A RM      : {POS_RA_RM}")
    print(f"  Region A Asst RM : {POS_RA_ASST_RM}")
    print(f"  Subregion A RM   : {POS_SRA_RM}")
    print(f"  WHA1 WM          : {POS_WHA1_WM}")
    print(f"  WHA2 WM          : {POS_WHA2_WM}")
    print(f"  WHA3 WM          : {POS_WHA3_WM}")
    print(f"  Factory B NM     : {POS_FB_NM}")
    print(f"  Region B1 RM     : {POS_RB1_RM}")
    print(f"  Subregion B1 RM  : {POS_SRB1_RM}")
    print(f"  WHB1-1 WM        : {POS_WHB11_WM}")
    print(f"  WHB1-2 WM        : {POS_WHB12_WM}")
    print(f"  Region B2 RM     : {POS_RB2_RM}")
    print(f"  WHB2-1 WM        : {POS_WHB21_WM}")
    print(f"  WHB2-2 WM        : {POS_WHB22_WM}")
    print(f"  T07 AU           : {POS_AU}")
    print(f"  T07 LM           : {POS_LM}")

    print()
    print("--PRODUCT IDs ─────────────────────────────────────────────────────────")
    print(f"  Steel Rod A  (T07-RM-001) : {PROD_P1}")
    print(f"  Copper Wire B(T07-RM-002) : {PROD_P2}")
    print(f"  Product Alpha(T07-FG-001) : {PROD_P3}")
    print(f"  Secure Item X(T07-FG-002) : {PROD_P4}  [controlled]")
    print(f"  Secure Item Y(T07-FG-003) : {PROD_P5}  [controlled]")

    print()
    print("--ROW COUNTS ──────────────────────────────────────────────────────────")
    for tbl, cnt in counts.items():
        print(f"  {tbl:<28}: {cnt}")
    print()
    print("Setup complete — Tenant 07 is ready for end-to-end testing.")
    print()
    print("Quick smoke-test commands:")
    print("  curl -s -X POST http://localhost:8000/api/v1/auth/token \\")
    print('       -H "Content-Type: application/json" \\')
    print('       -d \'{"dev_email":"admin@t07.com","dev_password":"Test@2026"}\'')
    print()


if __name__ == "__main__":
    asyncio.run(main())
