"""
ONE-TIME SETUP SCRIPT — Tenant 6 P2T, Part 2
==============================================
Runs AFTER Part 1 (Groups 0-9: org levels, tree, positions, personnel,
transfer types, approval rules, branding) has already completed for
tenant_id = e1badc24-5bdf-4ee6-bc1c-88d7c84a1bd7.

Seeds:
  PART 2  — Products (5 products, 1 category, 1 type code)
  PART 3  — Product approval overrides (controlled products, Design-B)
  PART 4  — Self-approval policies (transfer self-approval)
  PART 5  — Adjustment approval rules
  PART 6  — SAT_WHA3 satellite node + position + user + assignment
  PART 6b — SAT_WHA3 WM position + user + assignment
  PART 7  — Opening stock (RECEIVE ledger entries + balance upsert)
  PART 8  — tests/e2e/t6p2t_state.json update

Idempotent: safe to re-run — fixed UUIDs + ON CONFLICT DO UPDATE /
DELETE+INSERT / idempotency-key checks throughout.

Run:  python scripts/setup_t6p2t_part2.py
Requires: DATABASE_URL env var
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp1252 codec errors for non-ASCII chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ── Connection ──────────────────────────────────────────────────────────────
engine = create_async_engine(os.environ["DATABASE_URL"])
Session = async_sessionmaker(bind=engine, expire_on_commit=False)

# ══════════════════════════════════════════════════════════════════════════
# PART 1 — CONSTANTS
# ══════════════════════════════════════════════════════════════════════════
TENANT_ID = "aed68cc5-789f-4cb0-9ef5-9b6404267e42"
SA_USER   = "00000001-0a00-0000-0000-000000000001"  # platform SA — RLS context user
TA_USER   = "75960e66-39d1-4fa0-a4da-9fe4537f11fc"   # T6P2T TA — created_by attribution

# Nodes (from t6p2t_state.json)
NODE_A_FAC    = "bb874f9f-cc49-40a3-a814-ebeab83ffa25"   # L1
NODE_B_FAC    = "1fad3251-aba0-4930-b26c-e3e152577c5d"   # L1
NODE_A_REG    = "630aee08-424d-4146-b7c4-fab6e4cc208a"   # L2
NODE_B_REG    = "c678c8ea-595b-4f6a-9edd-a66b67557050"   # L2
NODE_WHA1     = "1eb94c52-4963-4355-8e54-0d9810eafb02"   # L3, parent=A_REG
NODE_WHA2     = "3996ffc4-4821-49ed-8717-d9c98025c695"   # L3, parent=A_REG
NODE_WHA3     = "266557a4-b2fb-438a-910e-c149bf35c8e9"   # L3, parent=A_REG
NODE_WHB1     = "c53b1fb3-10fa-453b-986b-6581c855d557"   # L3, parent=B_REG
NODE_WHB2     = "aeebb033-8594-44b5-932d-7bfd4411cdba"   # L3, parent=B_REG
NODE_SAT_WHA1 = "4ca4ea2a-512a-48a4-b01c-e72d20af3aff"   # L4, parent=WHA1
NODE_SAT_WHA2 = "80d2ba11-ac76-42ca-b834-f34913da58e3"   # L4, parent=WHA1
NODE_SAT_WHB1 = "7f0c4007-1488-4890-a551-12cc496ea289"   # L4, parent=WHB1
NODE_SAT_WHB2 = "230e9afa-d694-46f7-9eda-22ed9bc3dab3"   # L4, parent=WHB2

# NEW — SAT_WHA3 under WHA3 (L4 Satellite)
NODE_SAT_WHA3 = "e1badc24-0001-0004-0000-000000000001"

# Positions (from t6p2t_state.json)
POS_A_FAC_DIR = "0f1bd8cc-5ce3-4bab-b40c-03777fc2ad6c"   # NM @ A_FAC
POS_A_REG_MGR = "ce9e1ab6-d594-4dd9-aecd-4934fadfa432"   # RM @ A_REG
POS_WHA1_MGR  = "88d54a15-7a1f-4a0d-a597-e6518f1344bb"   # WM @ WHA1
POS_WHA2_MGR  = "c81e9288-5db1-4bbf-8ba8-5fa57a503cfa"   # WM @ WHA2
POS_WHA3_MGR  = "639a6396-edb8-4d48-86e0-df4a9650839e"   # WM @ WHA3
POS_B_FAC_DIR = "706c839a-d9ba-41e1-b1f5-b6445a3a50d4"   # NM @ B_FAC
POS_B_REG_MGR = "4ffbbb0f-f1ae-4271-a421-02aa1216f017"   # RM @ B_REG
POS_WHB1_MGR  = "78d8c59f-27e7-4365-b282-b8ef3a4af79b"   # WM @ WHB1
POS_WHB2_MGR  = "fdbe07cb-5650-4bad-b22d-799f5770b60f"   # WM @ WHB2

# NEW — SAT_WHA3 position and user
POS_SAT_WHA3_LEAD = "e1badc24-0002-0004-0000-000000000001"
USR_SAT_WHA3_LM   = "e1badc24-0003-0004-0000-000000000001"

# NEW — SAT_WHA3 WM position and user
POS_SAT_WHA3_WM = "e1badc24-0004-0004-0000-000000000001"
USR_SAT_WHA3_WM = "e1badc24-0005-0004-0000-000000000001"

# Products (fixed UUIDs for idempotency)
PROD_P1 = "e1badc24-0301-0000-0000-000000000001"  # Standard Bulk Item (regular)
PROD_P2 = "e1badc24-0301-0000-0000-000000000002"  # Premium Item (regular, higher value)
PROD_P3 = "e1badc24-0301-0000-0000-000000000003"  # Controlled-Always
PROD_P4 = "e1badc24-0301-0000-0000-000000000004"  # Controlled-Qty
PROD_P5 = "e1badc24-0301-0000-0000-000000000005"  # Factory-Specific A

# Product catalog support (category / type code) — created if missing
CAT_GENERAL = "e1badc24-0300-0000-0000-000000000001"
TC_STD      = "e1badc24-0300-0000-0000-000000000002"

PW_HASH = bcrypt.hashpw(b"Test@2026", bcrypt.gensalt(rounds=12)).decode("utf-8")
TODAY = date.today()


def uid() -> str:
    return str(uuid.uuid4())


def abort(part: str, err: Exception) -> None:
    print(f"\n[FATAL] {part} failed: {err}", file=sys.stderr)
    raise SystemExit(1)


async def set_rls(s, tenant_id: str, user_id: str = SA_USER) -> None:
    await s.execute(
        text(
            "SELECT set_config('app.current_tenant_id', :tid, true),"
            "       set_config('app.current_user_id',   :uid, true)"
        ),
        {"tid": tenant_id, "uid": user_id},
    )


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════
async def main() -> None:
    async with Session() as s:
        await set_rls(s, TENANT_ID)

        # ── PART 2 — PRODUCTS ────────────────────────────────────────────
        print("\n[PART 2] Creating products …")
        try:
            await s.execute(
                text("""
                    INSERT INTO product_categories (id, tenant_id, name, is_active)
                    VALUES (:id, :tid, :name, true)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """),
                {"id": CAT_GENERAL, "tid": TENANT_ID, "name": "General"},
            )
            await s.execute(
                text("""
                    INSERT INTO product_type_codes (id, tenant_id, code, description, is_active)
                    VALUES (:id, :tid, :code, :desc, true)
                    ON CONFLICT (id) DO UPDATE SET
                        code        = EXCLUDED.code,
                        description = EXCLUDED.description
                """),
                {"id": TC_STD, "tid": TENANT_ID, "code": "STD", "desc": "Standard"},
            )

            # (id, sku, name, uom, source_factory_id)
            products = [
                (PROD_P1, "T6P2T-STD-001", "Standard Bulk Item", "Unit", None),
                (PROD_P2, "T6P2T-STD-002", "Premium Item",       "Carton", None),
                (PROD_P3, "T6P2T-CON-001", "Secure Med-A",       "Unit", None),
                (PROD_P4, "T6P2T-CON-002", "Secure Med-B",       "Unit", None),
                (PROD_P5, "T6P2T-FAC-001", "Factory-A Special",  "Box", NODE_A_FAC),
            ]
            for p_id, sku, name, uom, src_fac in products:
                await s.execute(
                    text("""
                        INSERT INTO products
                            (id, tenant_id, sku, name, unit_of_measure,
                             category_id, type_code_id, batch_tracking, expiry_tracking,
                             source_factory_id, is_active, created_by)
                        VALUES
                            (:id, :tid, :sku, :name, :uom,
                             :cat, :tc, false, false,
                             :src_fac, true, :created_by)
                        ON CONFLICT (id) DO UPDATE SET
                            name              = EXCLUDED.name,
                            sku               = EXCLUDED.sku,
                            type_code_id      = EXCLUDED.type_code_id,
                            source_factory_id = EXCLUDED.source_factory_id
                    """),
                    {
                        "id": p_id, "tid": TENANT_ID, "sku": sku, "name": name,
                        "uom": uom, "cat": CAT_GENERAL, "tc": TC_STD,
                        "src_fac": src_fac, "created_by": TA_USER,
                    },
                )
            await s.commit()
            print(f"  [OK] 1 category + 1 type code + {len(products)} products created")
        except Exception as e:
            abort("PART 2", e)

        await set_rls(s, TENANT_ID)

        # ── PART 3 — PRODUCT APPROVAL OVERRIDES ─────────────────────────
        print("\n[PART 3] Creating product approval overrides …")
        try:
            overrides = [
                # (product_id, tx_type, threshold_type, qty_threshold, approver_pos_id)
                (PROD_P3, "PULL",       "ALWAYS",   None, POS_A_FAC_DIR),
                (PROD_P3, "PUSH",       "ALWAYS",   None, POS_A_FAC_DIR),
                (PROD_P3, "ADJUSTMENT", "ALWAYS",   None, POS_A_FAC_DIR),
                (PROD_P4, "PULL",       "QUANTITY", 50,   POS_A_REG_MGR),
                (PROD_P4, "ADJUSTMENT", "ALWAYS",   None, POS_A_REG_MGR),
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
                        "tid": TENANT_ID, "pid": p_id, "txtype": tx_type,
                        "ttype": ttype, "qty": qty_thr, "approver": approver_pos,
                        "created_by": TA_USER,
                    },
                )
            await s.commit()
            print(f"  [OK] {len(overrides)} product approval overrides set (P3 ALWAYS + P4 QUANTITY/ALWAYS)")
        except Exception as e:
            abort("PART 3", e)

        await set_rls(s, TENANT_ID)

        # ── PART 4 — SELF-APPROVAL POLICIES ─────────────────────────────
        print("\n[PART 4] Creating self-approval policies …")
        try:
            await s.execute(
                text("DELETE FROM self_approval_policies WHERE tenant_id = :tid"),
                {"tid": TENANT_ID},
            )
            sap_rows = [
                # (role_code, level_number, qty_limit) — None = unlimited
                ("NM", 1, None),
                ("RM", 2, 500),
                ("WM", 3, 200),
                ("LM", 4, 100),
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
                             ARRAY['PULL','PUSH','SISTER','ADJUSTMENT']::VARCHAR(20)[],
                             'QUANTITY', :qty, true)
                    """),
                    {"tid": TENANT_ID, "role": role_code, "lvl": level_num, "qty": qty_limit},
                )
            await s.commit()
            print(f"  [OK] {len(sap_rows)} self-approval policies set (NM/RM/WM/LM)")
        except Exception as e:
            abort("PART 4", e)

        await set_rls(s, TENANT_ID)

        # ── PART 5 — ADJUSTMENT APPROVAL RULES ──────────────────────────
        print("\n[PART 5] Creating adjustment approval rules …")
        try:
            await s.execute(
                text("DELETE FROM adjustment_approval_rules WHERE tenant_id = :tid"),
                {"tid": TENANT_ID},
            )
            adj_rows = [
                # (role_code, level_number, qty_limit, approver_position_id)
                ("NM", 1, None, None),
                ("RM", 2, 500,  None),
                ("WM", 3, 200,  POS_A_FAC_DIR),
                ("LM", 4, 100,  POS_WHA1_MGR),
            ]
            for role_code, level_num, qty_limit, approver_pos in adj_rows:
                await s.execute(
                    text("""
                        INSERT INTO adjustment_approval_rules
                            (tenant_id, role_code, level_number,
                             mode, threshold_type, qty_limit,
                             approver_position_id, priority, is_active)
                        VALUES
                            (:tid, :role, :lvl,
                             'GLOBAL', 'QUANTITY', :qty,
                             :approver, 1, true)
                    """),
                    {
                        "tid": TENANT_ID, "role": role_code, "lvl": level_num,
                        "qty": qty_limit, "approver": approver_pos,
                    },
                )
            await s.commit()
            print(f"  [OK] {len(adj_rows)} adjustment approval rules set (NM/RM/WM/LM)")
        except Exception as e:
            abort("PART 5", e)

        await set_rls(s, TENANT_ID)

        # ── PART 6 — SAT_WHA3 NODE + POSITION + USER ────────────────────
        print("\n[PART 6] Creating SAT_WHA3 satellite node, position, and user …")
        try:
            # 6a. Org node
            await s.execute(
                text("""
                    INSERT INTO organization_node
                        (id, tenant_id, name, code, hierarchy_level,
                         parent_node_id, is_stock_holding, is_active)
                    VALUES
                        (:id, :tid, :name, :code, 4,
                         :parent, true, true)
                    ON CONFLICT (id) DO UPDATE SET
                        name      = EXCLUDED.name,
                        is_active = EXCLUDED.is_active
                """),
                {
                    "id": NODE_SAT_WHA3, "tid": TENANT_ID,
                    "name": "Satellite WHA3 Depot", "code": "SAT-WHA3",
                    "parent": NODE_WHA3,
                },
            )

            # 6b. Position
            await s.execute(
                text("""
                    INSERT INTO positions
                        (id, tenant_id, node_id, title, role_code,
                         reports_to_position_id, is_active)
                    VALUES
                        (:id, :tid, :nid, :title, 'LM',
                         :rpts, true)
                    ON CONFLICT (id) DO UPDATE SET
                        title     = EXCLUDED.title,
                        role_code = EXCLUDED.role_code
                """),
                {
                    "id": POS_SAT_WHA3_LEAD, "tid": TENANT_ID, "nid": NODE_SAT_WHA3,
                    "title": "SAT_WHA3 Depot Lead", "rpts": POS_WHA3_MGR,
                },
            )

            # 6c. User
            email = "lm_satwha3@t6p2t.com"
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
                         NULL, :created_by)
                    ON CONFLICT (id) DO UPDATE SET
                        email         = EXCLUDED.email,
                        full_name     = EXCLUDED.full_name,
                        password_hash = EXCLUDED.password_hash
                """),
                {
                    "id": USR_SAT_WHA3_LM, "tid": TENANT_ID, "sub": cognito_sub,
                    "email": email, "name": "LM SAT WHA3", "pw": PW_HASH,
                    "created_by": TA_USER,
                },
            )

            # 6d. Personnel position assignment (PRIMARY)
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
                    "id": uid(), "tid": TENANT_ID, "uid": USR_SAT_WHA3_LM,
                    "pid": POS_SAT_WHA3_LEAD, "assigned_by": TA_USER,
                },
            )
            await s.commit()
            print("  [OK] SAT_WHA3 node + position + user + PRIMARY assignment created")
        except Exception as e:
            abort("PART 6", e)

        await set_rls(s, TENANT_ID)

        # ── PART 6b — SAT_WHA3 WM POSITION + USER ───────────────────────
        print("\n[PART 6b] Creating SAT_WHA3 WM position and user …")
        try:
            # 6b-i. Position: WM at SAT_WHA3, reports to WHA3_mgr (parent WM)
            await s.execute(
                text("""
                    INSERT INTO positions
                        (id, tenant_id, node_id, title, role_code,
                         reports_to_position_id, is_active)
                    VALUES
                        (:id, :tid, :nid, :title, 'WM',
                         :rpts, true)
                    ON CONFLICT (id) DO UPDATE SET
                        title     = EXCLUDED.title,
                        role_code = EXCLUDED.role_code
                """),
                {
                    "id": POS_SAT_WHA3_WM, "tid": TENANT_ID, "nid": NODE_SAT_WHA3,
                    "title": "SAT_WHA3 Warehouse Manager", "rpts": POS_WHA3_MGR,
                },
            )

            # 6b-ii. User: wm_satwha3@t6p2t.com
            email = "wm_satwha3@t6p2t.com"
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
                         NULL, :created_by)
                    ON CONFLICT (id) DO UPDATE SET
                        email         = EXCLUDED.email,
                        full_name     = EXCLUDED.full_name,
                        password_hash = EXCLUDED.password_hash
                """),
                {
                    "id": USR_SAT_WHA3_WM, "tid": TENANT_ID, "sub": cognito_sub,
                    "email": email, "name": "SAT WHA3 Warehouse Manager", "pw": PW_HASH,
                    "created_by": TA_USER,
                },
            )

            # 6b-iii. Personnel position assignment (PRIMARY)
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
                    "id": uid(), "tid": TENANT_ID, "uid": USR_SAT_WHA3_WM,
                    "pid": POS_SAT_WHA3_WM, "assigned_by": TA_USER,
                },
            )
            await s.commit()
            print("  [OK] SAT_WHA3 WM position + user + PRIMARY assignment created")
        except Exception as e:
            abort("PART 6b", e)

        await set_rls(s, TENANT_ID)

        # ── PART 7 — OPENING STOCK ───────────────────────────────────────
        print("\n[PART 7] Seeding opening stock …")
        try:
            # (product_id, node_id, qty)
            opening_stock = [
                (PROD_P1, NODE_A_FAC,    2000),
                (PROD_P1, NODE_A_REG,    1500),
                (PROD_P1, NODE_WHA1,     800),
                (PROD_P1, NODE_WHA2,     600),
                (PROD_P1, NODE_WHA3,     500),
                (PROD_P1, NODE_WHB1,     700),
                (PROD_P1, NODE_WHB2,     400),
                (PROD_P1, NODE_SAT_WHA1, 300),
                (PROD_P1, NODE_SAT_WHA2, 200),
                (PROD_P1, NODE_SAT_WHB1, 250),
                (PROD_P1, NODE_SAT_WHB2, 150),
                (PROD_P1, NODE_SAT_WHA3, 180),

                (PROD_P2, NODE_A_FAC,    500),
                (PROD_P2, NODE_WHA1,     200),
                (PROD_P2, NODE_WHA2,     150),
                (PROD_P2, NODE_WHB1,     180),

                (PROD_P3, NODE_A_FAC,    400),
                (PROD_P3, NODE_WHA1,     100),

                (PROD_P4, NODE_A_FAC,    300),
                (PROD_P4, NODE_WHA1,     80),

                (PROD_P5, NODE_A_FAC,    600),
                (PROD_P5, NODE_WHA1,     200),
                # P5 @ NODE_B_FAC deliberately NOT seeded — factory-specific
                # constraint test relies on zero stock on the B-side.
            ]

            tx_count = 0
            skipped = 0
            for prod_id, node_id, qty in opening_stock:
                ikey = f"t6p2t:seed:receipt:{prod_id[:8]}:{node_id[:8]}"

                existing = (await s.execute(
                    text("SELECT 1 FROM inventory_transactions "
                         "WHERE tenant_id=:tid AND idempotency_key=:ikey LIMIT 1"),
                    {"tid": TENANT_ID, "ikey": ikey},
                )).fetchone()
                if existing:
                    skipped += 1
                    continue

                tx_id = uid()
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
                        "id": tx_id, "td": TODAY, "tid": TENANT_ID,
                        "pid": prod_id, "wid": node_id, "qty": qty,
                        "ikey": ikey, "uid": TA_USER,
                    },
                )

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
                    {"tid": TENANT_ID, "pid": prod_id, "wid": node_id, "qty": qty},
                )
                tx_count += 1

            await s.commit()
            if skipped:
                print(f"  [skip] {skipped} stock entries already existed — skipped")
            print(f"  [OK] {tx_count} RECEIVE transactions seeded")
        except Exception as e:
            abort("PART 7", e)

    await engine.dispose()

    # ── PART 8 — UPDATE t6p2t_state.json ────────────────────────────────
    print("\n[PART 8] Updating tests/e2e/t6p2t_state.json …")
    try:
        state_path = Path(__file__).resolve().parent.parent / "tests" / "e2e" / "t6p2t_state.json"
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        state["nodes"]["SAT_WHA3"] = NODE_SAT_WHA3
        state["positions"]["SAT_WHA3_lead"] = POS_SAT_WHA3_LEAD
        state["users"]["lm_satwha3"] = {
            "id": USR_SAT_WHA3_LM,
            "email": "lm_satwha3@t6p2t.com",
            "password": "Test@2026",
            "assignment_id": None,
        }
        state["positions"]["SAT_WHA3_wm"] = POS_SAT_WHA3_WM
        state["users"]["wm_satwha3"] = {
            "id": USR_SAT_WHA3_WM,
            "email": "wm_satwha3@t6p2t.com",
            "password": "Test@2026",
            "assignment_id": None,
        }
        state["products"] = {
            "P1": PROD_P1,
            "P2": PROD_P2,
            "P3": PROD_P3,
            "P4": PROD_P4,
            "P5": PROD_P5,
        }

        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  [OK] {state_path} updated")
    except Exception as e:
        abort("PART 8", e)

    print()
    print("=" * 80)
    print("  T6P2T PART 2 SETUP COMPLETE")
    print("=" * 80)
    print(f"  Tenant ID       : {TENANT_ID}")
    print(f"  SAT_WHA3 node   : {NODE_SAT_WHA3}")
    print(f"  SAT_WHA3 lead   : {POS_SAT_WHA3_LEAD}")
    print(f"  lm_satwha3 user : {USR_SAT_WHA3_LM}  (lm_satwha3@t6p2t.com / Test@2026)")
    print(f"  SAT_WHA3 WM pos : {POS_SAT_WHA3_WM}")
    print(f"  wm_satwha3 user : {USR_SAT_WHA3_WM}  (wm_satwha3@t6p2t.com / Test@2026)")
    print(f"  Products        : P1={PROD_P1} P2={PROD_P2} P3={PROD_P3} P4={PROD_P4} P5={PROD_P5}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
