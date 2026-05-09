"""
Seed demo data for SMART Inventory Tracker portal.

Creates:
  - SA user: smartadmin@smart-inventory.com
  - Tenant: Addis Water (PRODUCER) — main production + 4 WHs + 1 sub-WH, 10 products, 7 users
  - Tenant: Muger Cement (PRODUCER) — 2 production centers + 4 WHs, 10 products, 7 users

Run after migrations and seed_permissions.py:
  python scripts/seed_demo_data.py

Requires DATABASE_URL env var (injected by ECS at runtime, or fetched from Secrets Manager in CI).
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ─── Connection ────────────────────────────────────────────────────────────────

engine = create_async_engine(os.environ["DATABASE_URL"])
Session = async_sessionmaker(bind=engine, expire_on_commit=False)

# ─── Tenant definitions ────────────────────────────────────────────────────────

PLAN_ID = str(uuid.uuid4())  # placeholder plan

TENANTS = [
    {
        "id": "10000001-0000-0000-0000-000000000001",
        "name": "Addis Water",
        "organisation_type": "PRODUCER",
        "default_locale": "am",
        "feature_flags": {"LOGISTICS": False, "AI_ANALYTICS": False, "ADVANCED_BATCH_TRACKING": True, "FLEET_MANAGEMENT": False},
        "approval_thresholds": {"inventory:adjust": {"low": 100, "medium": 500}},
        "sku_cap": 100,
    },
    {
        "id": "10000002-0000-0000-0000-000000000001",
        "name": "Muger Cement",
        "organisation_type": "PRODUCER",
        "default_locale": "am",
        "feature_flags": {"LOGISTICS": False, "AI_ANALYTICS": False, "ADVANCED_BATCH_TRACKING": False, "FLEET_MANAGEMENT": False},
        "approval_thresholds": {"inventory:adjust": {"low": 100, "medium": 500}},
        "sku_cap": 50,
    },
]

# ─── Warehouses ────────────────────────────────────────────────────────────────

WAREHOUSES = {
    "10000001-0000-0000-0000-000000000001": [
        {"id": "20000001-aw00-0000-0000-000000000001", "name": "Main Production Center", "parent_id": None, "location": "Addis Ababa Industrial Zone"},
        {"id": "20000001-aw00-0000-0000-000000000002", "name": "North WH",               "parent_id": None, "location": "Gondar"},
        {"id": "20000001-aw00-0000-0000-000000000003", "name": "North-Subcenter WH",      "parent_id": "20000001-aw00-0000-0000-000000000002", "location": "Bahir Dar"},
        {"id": "20000001-aw00-0000-0000-000000000004", "name": "South WH",               "parent_id": None, "location": "Hawassa"},
        {"id": "20000001-aw00-0000-0000-000000000005", "name": "East WH",                "parent_id": None, "location": "Dire Dawa"},
        {"id": "20000001-aw00-0000-0000-000000000006", "name": "West WH",                "parent_id": None, "location": "Jimma"},
    ],
    "10000002-0000-0000-0000-000000000001": [
        {"id": "20000002-mc00-0000-0000-000000000001", "name": "Harar Production Center", "parent_id": None, "location": "Harar, Harari Region"},
        {"id": "20000002-mc00-0000-0000-000000000002", "name": "Ambo Production Center",  "parent_id": None, "location": "Ambo, West Shewa"},
        {"id": "20000002-mc00-0000-0000-000000000003", "name": "Kombolcha WH",            "parent_id": None, "location": "Kombolcha, Amhara"},
        {"id": "20000002-mc00-0000-0000-000000000004", "name": "Mekele WH",              "parent_id": None, "location": "Mekele, Tigray"},
        {"id": "20000002-mc00-0000-0000-000000000005", "name": "Dire Dawa WH",           "parent_id": None, "location": "Dire Dawa"},
        {"id": "20000002-mc00-0000-0000-000000000006", "name": "Hawassa WH",             "parent_id": None, "location": "Hawassa, Sidama"},
    ],
}

# ─── Products ──────────────────────────────────────────────────────────────────

AW_PRODS = [
    {"sku": "AW-500-P6",   "name": "Pure Water 500ml — Pack of 6",            "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 500},
    {"sku": "AW-500-P12",  "name": "Pure Water 500ml — Pack of 12",           "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 300},
    {"sku": "AW-500-P24",  "name": "Pure Water 500ml — Pack of 24",           "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 200},
    {"sku": "AW-1L-P6",    "name": "Pure Water 1L — Pack of 6",               "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 400},
    {"sku": "AW-1L-P12",   "name": "Pure Water 1L — Pack of 12",              "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 250},
    {"sku": "AW-1L-P24",   "name": "Pure Water 1L — Pack of 24",              "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 150},
    {"sku": "AW-1.5L-P6",  "name": "Pure Water 1.5L — Pack of 6",             "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 300},
    {"sku": "AW-1.5L-P12", "name": "Pure Water 1.5L — Pack of 12",            "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 200},
    {"sku": "AW-SP500-P6", "name": "Sparkling Water 500ml — Pack of 6",        "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 100},
    {"sku": "AW-SP1L-P6",  "name": "Sparkling Water 1L — Pack of 6",           "uom": "Pack", "batch": True,  "expiry": True,  "reorder": 80},
]

MC_PRODS = [
    {"sku": "MC-OPC42N-25", "name": "OPC Grade 42.5N — 25kg Bag",                        "uom": "Bag",  "batch": False, "expiry": False, "reorder": 2000},
    {"sku": "MC-OPC42N-50", "name": "OPC Grade 42.5N — 50kg Bag",                        "uom": "Bag",  "batch": False, "expiry": False, "reorder": 1500},
    {"sku": "MC-OPC32R-25", "name": "OPC Grade 32.5R — 25kg Bag",                        "uom": "Bag",  "batch": False, "expiry": False, "reorder": 1500},
    {"sku": "MC-OPC32R-50", "name": "OPC Grade 32.5R — 50kg Bag",                        "uom": "Bag",  "batch": False, "expiry": False, "reorder": 1000},
    {"sku": "MC-PPC-25",    "name": "Portland Pozzolana Cement (PPC) — 25kg Bag",         "uom": "Bag",  "batch": False, "expiry": False, "reorder": 1200},
    {"sku": "MC-PPC-50",    "name": "Portland Pozzolana Cement (PPC) — 50kg Bag",         "uom": "Bag",  "batch": False, "expiry": False, "reorder": 800},
    {"sku": "MC-SRC-25",    "name": "Sulphate Resistant Cement (SRC) — 25kg Bag",         "uom": "Bag",  "batch": False, "expiry": False, "reorder": 500},
    {"sku": "MC-SRC-50",    "name": "Sulphate Resistant Cement (SRC) — 50kg Bag",         "uom": "Bag",  "batch": False, "expiry": False, "reorder": 300},
    {"sku": "MC-WPC-25",    "name": "White Portland Cement (WPC) — 25kg Bag",             "uom": "Bag",  "batch": False, "expiry": False, "reorder": 200},
    {"sku": "MC-WPC-50",    "name": "White Portland Cement (WPC) — 50kg Bag",             "uom": "Bag",  "batch": False, "expiry": False, "reorder": 150},
]

PRODUCTS = {
    "10000001-0000-0000-0000-000000000001": AW_PRODS,
    "10000002-0000-0000-0000-000000000001": MC_PRODS,
}

# ─── Users ────────────────────────────────────────────────────────────────────

SA_USER = {
    "id": "00000001-sa00-0000-0000-000000000001",
    "email": "smartadmin@smart-inventory.com",
    "name": "System Administrator",
    "role": "SA",
    "cognito_sub": "sa-cognito-sub-001",
    "tenant_id": None,
    "warehouse_id": None,
}

AW_USERS = [
    {"id": "00000001-aw01-0000-0000-000000000001", "email": "admin@addis-water.com",       "name": "Yohannes Tesfaye", "role": "TA", "wh": None},
    {"id": "00000001-aw02-0000-0000-000000000001", "email": "production@addis-water.com",  "name": "Selam Bekele",     "role": "NM", "wh": "20000001-aw00-0000-0000-000000000001"},
    {"id": "00000001-aw03-0000-0000-000000000001", "email": "north.wm@addis-water.com",    "name": "Hailu Tadesse",    "role": "WM", "wh": "20000001-aw00-0000-0000-000000000002"},
    {"id": "00000001-aw04-0000-0000-000000000001", "email": "northsub.wm@addis-water.com", "name": "Tigist Alemu",     "role": "WM", "wh": "20000001-aw00-0000-0000-000000000003"},
    {"id": "00000001-aw05-0000-0000-000000000001", "email": "south.wm@addis-water.com",    "name": "Dawit Girma",      "role": "WM", "wh": "20000001-aw00-0000-0000-000000000004"},
    {"id": "00000001-aw06-0000-0000-000000000001", "email": "east.wm@addis-water.com",     "name": "Fatuma Hassan",    "role": "WM", "wh": "20000001-aw00-0000-0000-000000000005"},
    {"id": "00000001-aw07-0000-0000-000000000001", "email": "west.wm@addis-water.com",     "name": "Abebe Worku",      "role": "WM", "wh": "20000001-aw00-0000-0000-000000000006"},
]

MC_USERS = [
    {"id": "00000002-mc01-0000-0000-000000000001", "email": "admin@muger-cement.com",       "name": "Abeba Haile",      "role": "TA", "wh": None},
    {"id": "00000002-mc02-0000-0000-000000000001", "email": "harar.pm@muger-cement.com",    "name": "Biruk Mengistu",   "role": "NM", "wh": "20000002-mc00-0000-0000-000000000001"},
    {"id": "00000002-mc03-0000-0000-000000000001", "email": "ambo.pm@muger-cement.com",     "name": "Meseret Tadesse",  "role": "NM", "wh": "20000002-mc00-0000-0000-000000000002"},
    {"id": "00000002-mc04-0000-0000-000000000001", "email": "kombolcha.wm@muger-cement.com","name": "Getnet Assefa",    "role": "WM", "wh": "20000002-mc00-0000-0000-000000000003"},
    {"id": "00000002-mc05-0000-0000-000000000001", "email": "mekele.wm@muger-cement.com",   "name": "Hiwot Gebre",      "role": "WM", "wh": "20000002-mc00-0000-0000-000000000004"},
    {"id": "00000002-mc06-0000-0000-000000000001", "email": "diredawa.wm@muger-cement.com", "name": "Abdulaziz Hassen", "role": "WM", "wh": "20000002-mc00-0000-0000-000000000005"},
    {"id": "00000002-mc07-0000-0000-000000000001", "email": "hawassa.wm@muger-cement.com",  "name": "Tigabu Tesfay",    "role": "WM", "wh": "20000002-mc00-0000-0000-000000000006"},
]

USERS_BY_TENANT = {
    "10000001-0000-0000-0000-000000000001": AW_USERS,
    "10000002-0000-0000-0000-000000000001": MC_USERS,
}

# ─── Sample inventory transactions ────────────────────────────────────────────

INITIAL_STOCK = {
    "10000001-0000-0000-0000-000000000001": {
        "AW-500-P6":   {"20000001-aw00-0000-0000-000000000001": 8400, "20000001-aw00-0000-0000-000000000002": 1200, "20000001-aw00-0000-0000-000000000003": 350,  "20000001-aw00-0000-0000-000000000004": 980,  "20000001-aw00-0000-0000-000000000005": 760,  "20000001-aw00-0000-0000-000000000006": 540},
        "AW-500-P12":  {"20000001-aw00-0000-0000-000000000001": 5200, "20000001-aw00-0000-0000-000000000002": 840,  "20000001-aw00-0000-0000-000000000003": 210,  "20000001-aw00-0000-0000-000000000004": 620,  "20000001-aw00-0000-0000-000000000005": 490,  "20000001-aw00-0000-0000-000000000006": 380},
        "AW-1L-P6":    {"20000001-aw00-0000-0000-000000000001": 6800, "20000001-aw00-0000-0000-000000000002": 960,  "20000001-aw00-0000-0000-000000000003": 280,  "20000001-aw00-0000-0000-000000000004": 740,  "20000001-aw00-0000-0000-000000000005": 620,  "20000001-aw00-0000-0000-000000000006": 480},
    },
    "10000002-0000-0000-0000-000000000001": {
        "MC-OPC42N-25": {"20000002-mc00-0000-0000-000000000001": 18500, "20000002-mc00-0000-0000-000000000002": 21000, "20000002-mc00-0000-0000-000000000003": 4200, "20000002-mc00-0000-0000-000000000004": 3800, "20000002-mc00-0000-0000-000000000005": 5100, "20000002-mc00-0000-0000-000000000006": 4600},
        "MC-OPC42N-50": {"20000002-mc00-0000-0000-000000000001": 12400, "20000002-mc00-0000-0000-000000000002": 15600, "20000002-mc00-0000-0000-000000000003": 3100, "20000002-mc00-0000-0000-000000000004": 2800, "20000002-mc00-0000-0000-000000000005": 3700, "20000002-mc00-0000-0000-000000000006": 3300},
        "MC-PPC-25":    {"20000002-mc00-0000-0000-000000000001": 8100,  "20000002-mc00-0000-0000-000000000002": 9600,  "20000002-mc00-0000-0000-000000000003": 1800, "20000002-mc00-0000-0000-000000000004": 1600, "20000002-mc00-0000-0000-000000000005": 2200, "20000002-mc00-0000-0000-000000000006": 1900},
    },
}


# ─── Seed functions ────────────────────────────────────────────────────────────

async def seed() -> None:
    async with Session() as s:
        # Plan
        await s.execute(text(
            "INSERT INTO plans (id, name, sku_limit) VALUES (:id, :name, :lim) ON CONFLICT DO NOTHING"
        ), {"id": PLAN_ID, "name": "Enterprise", "lim": None})

        # SA user (no tenant)
        await upsert_user(s, SA_USER, None)

        for tenant in TENANTS:
            tid = tenant["id"]
            print(f"\n[{tenant['name']}]")

            # Tenant
            await s.execute(text("""
                INSERT INTO tenants (id, name, organisation_type, plan_id, feature_flags,
                    approval_thresholds, default_locale, onboarding_complete, sku_cap)
                VALUES (:id, :name, :org_type, :plan_id, :flags::jsonb, :thresholds::jsonb,
                    :locale, true, :sku_cap)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, feature_flags = EXCLUDED.feature_flags
            """), {
                "id": tid, "name": tenant["name"], "org_type": tenant["organisation_type"],
                "plan_id": PLAN_ID, "flags": json.dumps(tenant["feature_flags"]),
                "thresholds": json.dumps(tenant["approval_thresholds"]),
                "locale": tenant["default_locale"], "sku_cap": tenant.get("sku_cap"),
            })
            print(f"  ✓ Tenant created")

            # RLS context
            await s.execute(text(
                "SELECT set_config('app.current_tenant_id', :tid, true), "
                "       set_config('app.current_user_id', '00000001-sa00-0000-0000-000000000001', true)"
            ), {"tid": tid})

            # Warehouses
            for wh in WAREHOUSES[tid]:
                await s.execute(text("""
                    INSERT INTO warehouses (id, tenant_id, name, parent_id, address)
                    VALUES (:id, :tid, :name, :parent, :addr)
                    ON CONFLICT (id) DO NOTHING
                """), {"id": wh["id"], "tid": tid, "name": wh["name"],
                       "parent": wh["parent_id"], "addr": wh["location"]})
            print(f"  ✓ {len(WAREHOUSES[tid])} warehouses created")

            # Products
            for prod in PRODUCTS[tid]:
                prod_id = str(uuid.uuid4())
                await s.execute(text("""
                    INSERT INTO products (id, tenant_id, sku, name, unit_of_measure,
                        batch_tracking, expiry_tracking, reorder_point)
                    VALUES (:id, :tid, :sku, :name, :uom, :batch, :expiry, :reorder)
                    ON CONFLICT (tenant_id, sku) DO NOTHING
                """), {
                    "id": prod_id, "tid": tid, "sku": prod["sku"], "name": prod["name"],
                    "uom": prod["uom"], "batch": prod["batch"], "expiry": prod["expiry"],
                    "reorder": prod["reorder"],
                })
            print(f"  ✓ {len(PRODUCTS[tid])} products created")

            # Initial inventory transactions
            tx_date = date.today()
            system_user = "00000001-sa00-0000-0000-000000000001"
            if tid in INITIAL_STOCK:
                tx_count = 0
                for sku, wh_qtys in INITIAL_STOCK[tid].items():
                    # Look up product id
                    res = await s.execute(
                        text("SELECT id FROM products WHERE tenant_id=:tid AND sku=:sku"),
                        {"tid": tid, "sku": sku}
                    )
                    row = res.fetchone()
                    if not row:
                        continue
                    prod_id = str(row[0])
                    for wh_id, qty in wh_qtys.items():
                        ikey = f"seed:{tid}:{sku}:{wh_id}"
                        tx_id = str(uuid.uuid4())
                        await s.execute(text("""
                            INSERT INTO inventory_transactions
                            (id, transaction_date, tenant_id, type, product_id, warehouse_id,
                             quantity, idempotency_key, source, created_by)
                            VALUES (:id, :td, :tid, 'RECEIVE', :pid, :wid, :qty, :ikey, 'SEED', :uid)
                            ON CONFLICT DO NOTHING
                        """), {
                            "id": tx_id, "td": tx_date, "tid": tid,
                            "pid": prod_id, "wid": wh_id, "qty": qty,
                            "ikey": ikey, "uid": system_user,
                        })
                        await s.execute(text("""
                            INSERT INTO inventory_balances (tenant_id, product_id, warehouse_id, quantity)
                            VALUES (:tid, :pid, :wid, :qty)
                            ON CONFLICT (tenant_id, product_id, warehouse_id) WHERE lot_number IS NULL
                            DO UPDATE SET quantity = inventory_balances.quantity + EXCLUDED.quantity
                        """), {"tid": tid, "pid": prod_id, "wid": wh_id, "qty": qty})
                        tx_count += 1
                print(f"  ✓ {tx_count} initial stock transactions seeded")

            # Users
            for u in USERS_BY_TENANT[tid]:
                await upsert_user(s, u, tid)
            print(f"  ✓ {len(USERS_BY_TENANT[tid])} users created")

        await s.commit()
        print("\nDemo data seeded successfully.")
        print("\n── Login credentials ─────────────────────────────────────────────")
        print("SA Admin:          smartadmin@smart-inventory.com  /  SmartAdmin@2026")
        print("Addis Water Admin: admin@addis-water.com           /  AddisWater@2026")
        print("Muger Cement:      admin@muger-cement.com          /  MugerCement@2026")
        print("(All WM accounts use the tenant password listed above)")
        print("─────────────────────────────────────────────────────────────────\n")

    await engine.dispose()


async def upsert_user(s, u: dict, tenant_id: str | None) -> None:
    await s.execute(text("""
        INSERT INTO users (id, tenant_id, cognito_sub, email, full_name, role, warehouse_id)
        VALUES (:id, :tid, :sub, :email, :name, :role, :wh)
        ON CONFLICT (cognito_sub) DO UPDATE SET
            full_name = EXCLUDED.full_name, role = EXCLUDED.role
    """), {
        "id": u["id"],
        "tid": tenant_id,
        "sub": u.get("cognito_sub", u["email"].replace("@", "_").replace(".", "_")),
        "email": u["email"],
        "name": u["name"],
        "role": u["role"],
        "wh": u.get("wh"),
    })


if __name__ == "__main__":
    asyncio.run(seed())
