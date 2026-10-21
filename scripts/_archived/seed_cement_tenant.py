"""Seed script — Ethiopian Cement Hub (RETAILER/HYBRID tenant).

A multi-brand cement distribution company stocking products from all major
Ethiopian cement producers: Dangote, Derba, Mugher, Messebo, Habesha,
National, and Lemi.

Data ported from reference seed (seed.py / seed_new_tenants.py):
  - LedgerEventType.production  → transaction_type RECEIVE
  - LedgerEventType.transfer    → transaction_type RECEIVE  (allocation received)
  - LedgerEventType.shipment_out → TRANSFER_OUT (created as a transfer_order)
  - LedgerEventType.manual_adjustment → ADJUSTMENT

Run after migrations and seed_permissions.py:
    python scripts/seed_cement_tenant.py

Requires DATABASE_URL in environment (injected by ECS or fetched from Secrets Manager in CI).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

engine = create_async_engine(os.environ["DATABASE_URL"])
Session = async_sessionmaker(bind=engine, expire_on_commit=False)

PLAN_ID = str(uuid.uuid4())
SYSTEM_USER = "00000001-0a00-0000-0000-000000000001"  # SA created by seed_demo_data.py


def uid() -> str:
    return str(uuid.uuid4())


async def get_or_create(session, table: str, lookup: dict, data: dict) -> dict:
    """Upsert helper: lookup by one column, insert with full data if missing."""
    col, val = next(iter(lookup.items()))
    row = (
        await session.execute(
            text(f"SELECT * FROM {table} WHERE {col} = :{col}"), {col: val}
        )
    ).fetchone()
    if row:
        return dict(row._mapping)
    await session.execute(
        text(
            f"INSERT INTO {table} ({', '.join(data.keys())}) VALUES ({', '.join(':' + k for k in data.keys())})"
        ),
        data,
    )
    result = (
        await session.execute(
            text(f"SELECT * FROM {table} WHERE {col} = :{col}"), {col: val}
        )
    ).fetchone()
    return dict(result._mapping)


async def seed() -> None:
    async with Session() as s:
        # ── Plan (placeholder) ───────────────────────────────────────────
        await s.execute(
            text(
                "INSERT INTO plans (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"
            ),
            {"id": PLAN_ID, "name": "Enterprise"},
        )

        # ── Tenant ───────────────────────────────────────────────────────
        import json

        tid = uid()
        tenant = await get_or_create(
            s,
            "tenants",
            {"slug": "eth-cement-hub"},
            {
                "id": tid,
                "name": "Ethiopian Cement Hub",
                "slug": "eth-cement-hub",
                "organisation_type": "HYBRID",
                "plan_id": PLAN_ID,
                "feature_flags": json.dumps(
                    {
                        "LOGISTICS": True,
                        "AI_ANALYTICS": True,
                        "ADVANCED_BATCH_TRACKING": False,
                        "FLEET_MANAGEMENT": True,
                    }
                ),
                "approval_thresholds": json.dumps(
                    {"inventory:adjust": {"low": 500, "medium": 5000}}
                ),
                "default_locale": "am",
                "onboarding_complete": True,
                "sku_cap": None,
                "is_active": True,
            },
        )
        tid = str(tenant["id"])
        print(f"Tenant: Ethiopian Cement Hub ({tid})")

        # RLS context for subsequent queries
        await s.execute(
            text(
                "SELECT set_config('app.current_tenant_id',:tid,true),"
                "       set_config('app.current_user_id',:uid,true)"
            ),
            {"tid": tid, "uid": SYSTEM_USER},
        )

        # ── Admin user ───────────────────────────────────────────────────
        admin = await get_or_create(
            s,
            "users",
            {"email": "admin@eth-cement-hub.et"},
            {
                "id": uid(),
                "tenant_id": tid,
                "cognito_sub": "eth-cement-hub-admin-sub",
                "email": "admin@eth-cement-hub.et",
                "full_name": "Ethiopian Cement Hub Admin",
                "role": "TA",
                "locale": "am",
                "is_active": True,
            },
        )
        aid = str(admin["id"])

        # Manager accounts per location
        managers = [
            ("addis.mgr@eth-cement-hub.et", "Addis Central Manager", "NM"),
            ("mekele.mgr@eth-cement-hub.et", "Mekele Regional Manager", "WM"),
            ("hawassa.mgr@eth-cement-hub.et", "Hawassa Regional Manager", "WM"),
            ("bahirdar.mgr@eth-cement-hub.et", "Bahir Dar Manager", "WM"),
            ("diredawa.mgr@eth-cement-hub.et", "Dire Dawa Manager", "WM"),
        ]
        for email, name, role in managers:
            await get_or_create(
                s,
                "users",
                {"email": email},
                {
                    "id": uid(),
                    "tenant_id": tid,
                    "cognito_sub": email.replace("@", "_"),
                    "email": email,
                    "full_name": name,
                    "role": role,
                    "locale": "am",
                    "is_active": True,
                },
            )
        await s.commit()
        print(f"  Users: {1 + len(managers)} created")

        # ── Products (17 cement SKUs from reference) ─────────────────────
        products_data = [
            # (name, sku, description)
            # Dangote
            (
                "Dangote OPC 42.5R",
                "DNG-OPC-42R",
                "Ordinary Portland Cement 42.5R – high early strength, bridges & high-rise. Mugher plant.",
                "bag",
                50,
            ),
            (
                "Dangote PPC 32.5R",
                "DNG-PPC-32R",
                "Portland Pozzolana Cement 32.5R – general construction, residential. Mugher plant.",
                "bag",
                50,
            ),
            (
                "Dangote 3X 42.5N",
                "DNG-3X-42N",
                "3X Cement 42.5N – Xtra strong, Xtra life, Xtra yield. Premium grade.",
                "bag",
                30,
            ),
            # Derba
            (
                "Derba OPC 42.5R",
                "DRB-OPC-42R",
                "Derba Medroc OPC 42.5R – structural & infrastructure. Derba plant, West Shewa.",
                "bag",
                50,
            ),
            (
                "Derba PPC 32.5R",
                "DRB-PPC-32R",
                "Derba Medroc PPC 32.5R – popular for residential construction.",
                "bag",
                50,
            ),
            # Mugher
            (
                "Mugher OPC 42.5N",
                "MGH-OPC-42N",
                "Mugher Cement OPC 42.5N – established brand, widely used in Addis Ababa.",
                "bag",
                50,
            ),
            (
                "Mugher PPC 32.5R",
                "MGH-PPC-32R",
                "Mugher PPC 32.5R – standard masonry & plastering grade.",
                "bag",
                50,
            ),
            (
                "Mugher PSC 42.5",
                "MGH-PSC-42",
                "Portland Slag Cement 42.5 – durable, harbour & dam projects.",
                "bag",
                20,
            ),
            # Messebo
            (
                "Messebo OPC 42.5R",
                "MSB-OPC-42R",
                "Messebo OPC 42.5R – Mekele factory, dominant in Tigray & northern regions.",
                "bag",
                50,
            ),
            (
                "Messebo PPC 32.5R",
                "MSB-PPC-32R",
                "Messebo PPC 32.5R – general purpose, Afar & northern Ethiopia.",
                "bag",
                50,
            ),
            (
                "Messebo RHC 52.5R",
                "MSB-RHC-52R",
                "Rapid Hardening Cement 52.5R – fast-track infrastructure, quick strength.",
                "bag",
                15,
            ),
            # Habesha
            (
                "Habesha PPC 32.5R",
                "HBS-PPC-32R",
                "Habesha Cement PPC 32.5R – Holeta plant, popular in Oromia & SNNPR.",
                "bag",
                50,
            ),
            (
                "Habesha OPC 42.5N",
                "HBS-OPC-42N",
                "Habesha OPC 42.5N – premium structural cement from Holeta plant.",
                "bag",
                30,
            ),
            # National
            (
                "National OPC 42.5R",
                "NAT-OPC-42R",
                "National Cement OPC 42.5R – Dire Dawa plant, dominates eastern Ethiopia.",
                "bag",
                50,
            ),
            (
                "National PPC 32.5R",
                "NAT-PPC-32R",
                "National Cement PPC 32.5R – cost-effective residential, eastern Ethiopia.",
                "bag",
                50,
            ),
            # Lemi (new entrant)
            (
                "Lemi OPC 42.5R",
                "LMI-OPC-42R",
                "Lemi National Cement OPC 42.5R – Amhara region, disrupting prices (ETB 1,500/bag).",
                "bag",
                80,
            ),
            (
                "Lemi PPC 32.5R",
                "LMI-PPC-32R",
                "Lemi PPC 32.5R – affordable grade driving market competition 2025-2026.",
                "bag",
                80,
            ),
        ]

        products: dict[str, str] = {}  # sku → id
        for name, sku, desc, uom, reorder_qty in products_data:
            row = await get_or_create(
                s,
                "products",
                {"sku": sku},
                {
                    "id": uid(),
                    "tenant_id": tid,
                    "sku": sku,
                    "name": name,
                    "description": desc,
                    "unit_of_measure": uom,
                    "batch_tracking": False,
                    "expiry_tracking": False,
                    "reorder_point": reorder_qty,
                    "reorder_quantity": reorder_qty * 4,
                    "is_active": True,
                    "created_by": aid,
                },
            )
            products[sku] = str(row["id"])
        await s.commit()
        print(f"  Products: {len(products_data)} ready")

        # ── Warehouses (18 locations) ─────────────────────────────────────
        warehouses_data = [
            # (name, code, warehouse_type, address)
            (
                "Addis Ababa Central Depot",
                "WH-ADD-01",
                "REGIONAL",
                "Akaki-Kaliti Sub-City, Addis Ababa",
            ),
            (
                "Addis Ababa Bole Depot",
                "WH-ADD-02",
                "RETAIL",
                "Bole Sub-City, near Bole International Airport",
            ),
            (
                "Addis Ababa Megenagna Depot",
                "WH-ADD-03",
                "RETAIL",
                "Megenagna, Yeka Sub-City, Addis Ababa",
            ),
            (
                "Dangote Mugher Factory",
                "WH-DNG-01",
                "FACTORY",
                "Mugher, West Shewa Zone, Oromia — 90 km from Addis Ababa",
            ),
            (
                "Derba Factory Depot",
                "WH-DRB-01",
                "FACTORY",
                "Derba, West Shewa Zone, Oromia",
            ),
            (
                "Mugher Cement Factory",
                "WH-MGH-01",
                "FACTORY",
                "Mugher Town, West Shewa Zone, Oromia",
            ),
            (
                "Messebo Mekele Factory",
                "WH-MSB-01",
                "FACTORY",
                "Mekele Industrial Zone, Tigray Region",
            ),
            (
                "Habesha Holeta Factory",
                "WH-HBS-01",
                "FACTORY",
                "Holeta Town, West Shewa Zone, Oromia — 35 km from Addis Ababa",
            ),
            (
                "National Cement Dire Dawa",
                "WH-NAT-01",
                "FACTORY",
                "Dire Dawa Industrial Zone",
            ),
            (
                "Lemi Amhara Factory",
                "WH-LMI-01",
                "FACTORY",
                "Lemi Township, North Shewa Zone, Amhara — 120 km from Addis Ababa",
            ),
            (
                "Hawassa Regional Depot",
                "WH-HWS-01",
                "REGIONAL",
                "Tabor Sub-City, Hawassa, SNNPR",
            ),
            (
                "Bahir Dar Regional Depot",
                "WH-BDR-01",
                "REGIONAL",
                "Belay Zeleke Area, Bahir Dar, Amhara",
            ),
            (
                "Mekele Regional Depot",
                "WH-MKL-01",
                "REGIONAL",
                "Industrial Zone, Mekele, Tigray",
            ),
            (
                "Jimma Regional Depot",
                "WH-JIM-01",
                "REGIONAL",
                "Jimma Town, Jimma Zone, Oromia",
            ),
            (
                "Dire Dawa Regional Depot",
                "WH-DDW-01",
                "REGIONAL",
                "Kezira Area, Dire Dawa",
            ),
            (
                "Gondar Distribution Center",
                "WH-GND-01",
                "REGIONAL",
                "Azezo, Gondar, Amhara Region",
            ),
            (
                "Adama (Nazret) Depot",
                "WH-ADM-01",
                "REGIONAL",
                "Adama, East Shewa Zone, Oromia — 100 km from Addis Ababa",
            ),
            (
                "Dessie Distribution Center",
                "WH-DSS-01",
                "REGIONAL",
                "Dessie, South Wollo Zone, Amhara",
            ),
        ]

        warehouses: dict[str, str] = {}  # code → id
        for name, code, wtype, address in warehouses_data:
            row = await get_or_create(
                s,
                "warehouses",
                {"code": code},
                {
                    "id": uid(),
                    "tenant_id": tid,
                    "name": name,
                    "code": code,
                    "warehouse_type": wtype,
                    "address": address,
                    "is_active": True,
                },
            )
            warehouses[code] = str(row["id"])
        await s.commit()
        print(f"  Warehouses: {len(warehouses_data)} ready")

        # ── Inventory transactions (initial stock) ────────────────────────
        today = date.today()

        def add_receive(sku: str, wh_code: str, qty: int, notes: str) -> None:
            pid = products.get(sku)
            wid = warehouses.get(wh_code)
            if not pid or not wid:
                print(f"  WARN: missing {sku} or {wh_code}")
                return
            ikey = f"seed:receive:{sku}:{wh_code}"
            tx_id = uid()
            asyncio.get_event_loop().run_until_complete(
                s.execute(
                    text("""
                    INSERT INTO inventory_transactions
                      (id, transaction_date, tenant_id, type, product_id, warehouse_id,
                       quantity, idempotency_key, source, created_by)
                    VALUES (:id, :td, :tid, 'RECEIVE', :pid, :wid, :qty, :ikey, 'SEED', :uid)
                    ON CONFLICT DO NOTHING
                """),
                    {
                        "id": tx_id,
                        "td": today,
                        "tid": tid,
                        "pid": pid,
                        "wid": wid,
                        "qty": qty,
                        "ikey": ikey,
                        "uid": aid,
                    },
                )
            )
            asyncio.get_event_loop().run_until_complete(
                s.execute(
                    text("""
                    INSERT INTO inventory_balances (tenant_id, product_id, warehouse_id, quantity)
                    VALUES (:tid, :pid, :wid, :qty)
                    ON CONFLICT (tenant_id, product_id, warehouse_id) WHERE lot_number IS NULL
                    DO UPDATE SET quantity = inventory_balances.quantity + EXCLUDED.quantity,
                                  updated_at = now()
                """),
                    {"tid": tid, "pid": pid, "wid": wid, "qty": qty},
                )
            )

        # Use an async approach instead
        async def recv(sku, wh_code, qty, notes=""):
            pid = products.get(sku)
            wid = warehouses.get(wh_code)
            if not pid or not wid:
                return
            ikey = f"seed:recv:{sku}:{wh_code}"
            await s.execute(
                text("""
                INSERT INTO inventory_transactions
                  (id, transaction_date, tenant_id, type, product_id, warehouse_id,
                   quantity, idempotency_key, source, created_by)
                VALUES (:id, :td, :tid, 'RECEIVE', :pid, :wid, :qty, :ikey, 'SEED', :uid)
                ON CONFLICT DO NOTHING
            """),
                {
                    "id": uid(),
                    "td": today,
                    "tid": tid,
                    "pid": pid,
                    "wid": wid,
                    "qty": qty,
                    "ikey": ikey,
                    "uid": aid,
                },
            )
            await s.execute(
                text("""
                INSERT INTO inventory_balances (tenant_id, product_id, warehouse_id, quantity)
                VALUES (:tid, :pid, :wid, :qty)
                ON CONFLICT (tenant_id, product_id, warehouse_id) WHERE lot_number IS NULL
                DO UPDATE SET quantity = inventory_balances.quantity + EXCLUDED.quantity,
                              updated_at = now()
            """),
                {"tid": tid, "pid": pid, "wid": wid, "qty": qty},
            )

        # Factory stock — production output (bags)
        await recv(
            "DNG-OPC-42R",
            "WH-DNG-01",
            45000,
            "Dangote OPC 42.5R production batch — April 2026",
        )
        await recv(
            "DNG-PPC-32R",
            "WH-DNG-01",
            38000,
            "Dangote PPC 32.5R production batch — April 2026",
        )
        await recv(
            "DNG-3X-42N", "WH-DNG-01", 22000, "Dangote 3X premium batch — April 2026"
        )
        await recv(
            "DRB-OPC-42R", "WH-DRB-01", 31000, "Derba OPC production — April 2026"
        )
        await recv(
            "DRB-PPC-32R", "WH-DRB-01", 42000, "Derba PPC production — April 2026"
        )
        await recv("MGH-OPC-42N", "WH-MGH-01", 28000, "Mugher OPC 42.5N monthly batch")
        await recv("MGH-PPC-32R", "WH-MGH-01", 35000, "Mugher PPC 32.5R monthly batch")
        await recv(
            "MGH-PSC-42", "WH-MGH-01", 8000, "Mugher PSC 42.5 — specialty order batch"
        )
        await recv(
            "MSB-OPC-42R",
            "WH-MSB-01",
            40000,
            "Messebo OPC 42.5R — Mekele factory output",
        )
        await recv(
            "MSB-PPC-32R",
            "WH-MSB-01",
            33000,
            "Messebo PPC 32.5R — Mekele factory output",
        )
        await recv(
            "MSB-RHC-52R",
            "WH-MSB-01",
            5000,
            "Messebo RHC 52.5R — special rapid-hardening batch",
        )
        await recv(
            "HBS-PPC-32R", "WH-HBS-01", 29000, "Habesha PPC — Holeta factory April 2026"
        )
        await recv(
            "HBS-OPC-42N", "WH-HBS-01", 18000, "Habesha OPC — Holeta factory April 2026"
        )
        await recv(
            "NAT-OPC-42R", "WH-NAT-01", 26000, "National Cement OPC — Dire Dawa plant"
        )
        await recv(
            "NAT-PPC-32R", "WH-NAT-01", 34000, "National Cement PPC — Dire Dawa plant"
        )
        await recv(
            "LMI-OPC-42R",
            "WH-LMI-01",
            55000,
            "Lemi new production run — disrupting market Q1 2026",
        )
        await recv(
            "LMI-PPC-32R",
            "WH-LMI-01",
            61000,
            "Lemi PPC high-volume — ETB 1,500/bag wholesale",
        )

        # Regional depot allocations (received as RECEIVE from factory transfers)
        await recv(
            "DNG-OPC-42R",
            "WH-ADD-01",
            8000,
            "Allocation from Dangote Mugher to Addis Central Depot",
        )
        await recv(
            "DRB-PPC-32R",
            "WH-ADD-01",
            6000,
            "Allocation from Derba to Addis Central Depot",
        )
        await recv(
            "MGH-OPC-42N",
            "WH-ADD-01",
            5500,
            "Allocation from Mugher to Addis Central Depot",
        )
        await recv(
            "LMI-PPC-32R",
            "WH-ADD-01",
            9000,
            "Lemi allocation to Addis Central — competitive pricing push",
        )
        await recv(
            "MSB-OPC-42R",
            "WH-MKL-01",
            7500,
            "Messebo allocation to Mekele Regional Depot",
        )
        await recv("MSB-PPC-32R", "WH-MKL-01", 6200, "Messebo PPC to Mekele Regional")
        await recv(
            "NAT-OPC-42R",
            "WH-DDW-01",
            5000,
            "National Cement allocation to Dire Dawa Depot",
        )
        await recv("NAT-PPC-32R", "WH-DDW-01", 7800, "National PPC to Dire Dawa Depot")
        await recv(
            "HBS-PPC-32R", "WH-HWS-01", 6500, "Habesha PPC allocation to Hawassa Depot"
        )
        await recv("DNG-PPC-32R", "WH-HWS-01", 4200, "Dangote PPC to Hawassa Depot")
        await recv(
            "LMI-OPC-42R",
            "WH-BDR-01",
            8800,
            "Lemi allocation to Bahir Dar — Amhara region proximity",
        )
        await recv("LMI-PPC-32R", "WH-BDR-01", 7600, "Lemi PPC to Bahir Dar Depot")
        await recv(
            "DRB-OPC-42R", "WH-ADM-01", 4500, "Derba allocation to Adama/Nazret Depot"
        )
        await recv("MGH-PPC-32R", "WH-ADM-01", 5100, "Mugher PPC to Adama Depot")
        await recv(
            "MSB-OPC-42R",
            "WH-GND-01",
            3800,
            "Messebo OPC to Gondar Distribution Center",
        )
        await recv(
            "LMI-PPC-32R",
            "WH-GND-01",
            5500,
            "Lemi PPC to Gondar — Amhara market expansion",
        )
        await recv(
            "DNG-OPC-42R", "WH-JIM-01", 3200, "Dangote allocation to Jimma Depot"
        )
        await recv(
            "HBS-PPC-32R",
            "WH-JIM-01",
            4100,
            "Habesha PPC to Jimma — Oromia distribution",
        )
        await s.commit()
        print(f"  Inventory: {35} RECEIVE transactions seeded")

        # ── Adjustments (damage, reconciliation) ─────────────────────────
        async def adjust(sku, wh_code, qty, notes):
            pid = products.get(sku)
            wid = warehouses.get(wh_code)
            if not pid or not wid:
                return
            # Negative adjustments are stored as ADJUSTMENT with negative quantity
            ikey = f"seed:adj:{sku}:{wh_code}:{notes[:20]}"
            await s.execute(
                text("""
                INSERT INTO inventory_transactions
                  (id, transaction_date, tenant_id, type, product_id, warehouse_id,
                   quantity, idempotency_key, source, created_by)
                VALUES (:id, :td, :tid, 'ADJUSTMENT', :pid, :wid, :qty, :ikey, 'SEED', :uid)
                ON CONFLICT DO NOTHING
            """),
                {
                    "id": uid(),
                    "td": today,
                    "tid": tid,
                    "pid": pid,
                    "wid": wid,
                    "qty": qty,
                    "ikey": ikey,
                    "uid": aid,
                },
            )
            # Update balance
            await s.execute(
                text("""
                INSERT INTO inventory_balances (tenant_id, product_id, warehouse_id, quantity)
                VALUES (:tid, :pid, :wid, :qty)
                ON CONFLICT (tenant_id, product_id, warehouse_id) WHERE lot_number IS NULL
                DO UPDATE SET quantity = inventory_balances.quantity + EXCLUDED.quantity,
                              updated_at = now()
            """),
                {"tid": tid, "pid": pid, "wid": wid, "qty": qty},
            )

        await adjust(
            "DNG-OPC-42R",
            "WH-ADD-01",
            -120,
            "Damaged bags — moisture exposure. Written off.",
        )
        await adjust(
            "MSB-PPC-32R",
            "WH-MKL-01",
            200,
            "Stock reconciliation — physical count higher than system.",
        )
        await adjust(
            "HBS-PPC-32R",
            "WH-HWS-01",
            -80,
            "Expired stock disposal — beyond shelf life.",
        )
        await adjust(
            "LMI-PPC-32R",
            "WH-BDR-01",
            350,
            "Bonus delivery from Lemi — goodwill allocation.",
        )
        await adjust(
            "NAT-OPC-42R",
            "WH-DDW-01",
            -150,
            "Return to factory — transit damage. RMA raised.",
        )
        await adjust(
            "MGH-PSC-42",
            "WH-ADD-01",
            500,
            "Special PSC allocation — Kality industrial project.",
        )
        await s.commit()
        print("  Adjustments: 6 created")

        # ── Transfer orders (shipments from reference) ────────────────────
        async def make_transfer(ref, src_code, dst_code, status, items, notes=""):
            src = warehouses.get(src_code)
            dst = warehouses.get(dst_code)
            if not src or not dst:
                print(f"  WARN: warehouse missing for {ref}")
                return
            to_id = uid()
            await s.execute(
                text("""
                INSERT INTO transfer_orders
                  (id, tenant_id, from_warehouse_id, to_warehouse_id,
                   status, reference_number, notes, created_by)
                VALUES (:id, :tid, :from_wh, :to_wh, :status, :ref, :notes, :uid)
                ON CONFLICT DO NOTHING
            """),
                {
                    "id": to_id,
                    "tid": tid,
                    "from_wh": src,
                    "to_wh": dst,
                    "status": status,
                    "ref": ref,
                    "notes": notes,
                    "uid": aid,
                },
            )
            for sku, qty in items:
                pid = products.get(sku)
                if pid:
                    await s.execute(
                        text("""
                        INSERT INTO transfer_order_lines
                          (id, transfer_order_id, tenant_id, product_id, quantity)
                        VALUES (:id, :toid, :tid, :pid, :qty)
                        ON CONFLICT DO NOTHING
                    """),
                        {
                            "id": uid(),
                            "toid": to_id,
                            "tid": tid,
                            "pid": pid,
                            "qty": qty,
                        },
                    )

        # Closed/received transfers (stock already moved — ledger reflects receipt above)
        await make_transfer(
            "SHIP-2026-001",
            "WH-DNG-01",
            "WH-ADD-01",
            "CLOSED",
            [("DNG-OPC-42R", 3000), ("DNG-PPC-32R", 2500)],
            "Dangote monthly allocation to Addis Central — March 2026. ETB 720/bag OPC.",
        )
        await make_transfer(
            "SHIP-2026-002",
            "WH-MSB-01",
            "WH-MKL-01",
            "CLOSED",
            [("MSB-OPC-42R", 4000), ("MSB-PPC-32R", 3000)],
            "Messebo regular supply to Mekele Regional Depot — March 2026.",
        )
        await make_transfer(
            "SHIP-2026-003",
            "WH-NAT-01",
            "WH-DDW-01",
            "CLOSED",
            [("NAT-OPC-42R", 2500), ("NAT-PPC-32R", 3500)],
            "National Cement to Dire Dawa Depot — March 2026.",
        )
        await make_transfer(
            "SHIP-2026-004",
            "WH-HBS-01",
            "WH-HWS-01",
            "CLOSED",
            [("HBS-PPC-32R", 3200), ("HBS-OPC-42N", 1800)],
            "Habesha supply to Hawassa — SNNPR market allocation April 2026.",
        )
        await make_transfer(
            "SHIP-2026-005",
            "WH-LMI-01",
            "WH-BDR-01",
            "CLOSED",
            [("LMI-OPC-42R", 4500), ("LMI-PPC-32R", 4000)],
            "Lemi Amhara push — Bahir Dar at ETB 1,500/bag. Major market disruption.",
        )
        await make_transfer(
            "SHIP-2026-006",
            "WH-DRB-01",
            "WH-ADM-01",
            "CLOSED",
            [("DRB-OPC-42R", 2200), ("DRB-PPC-32R", 2800)],
            "Derba to Adama/Nazret — serving East Shewa construction projects.",
        )

        # In-transit transfers
        await make_transfer(
            "SHIP-2026-007",
            "WH-DNG-01",
            "WH-JIM-01",
            "IN_TRANSIT",
            [("DNG-OPC-42R", 2000), ("DNG-PPC-32R", 1500)],
            "Dangote to Jimma — Oromia western corridor. Truck convoy, ETA 2 days.",
        )
        await make_transfer(
            "SHIP-2026-008",
            "WH-LMI-01",
            "WH-GND-01",
            "IN_TRANSIT",
            [("LMI-OPC-42R", 3500), ("LMI-PPC-32R", 4000)],
            "Lemi Gondar push — competing with Messebo in Amhara market. ETA 3 days.",
        )
        await make_transfer(
            "SHIP-2026-009",
            "WH-MSB-01",
            "WH-DSS-01",
            "IN_TRANSIT",
            [("MSB-OPC-42R", 2800), ("MSB-PPC-32R", 2200)],
            "Messebo to Dessie — Wollo region supply. Road via Kombolcha.",
        )
        await make_transfer(
            "SHIP-2026-010",
            "WH-MGH-01",
            "WH-ADD-02",
            "IN_TRANSIT",
            [("MGH-OPC-42N", 1800), ("MGH-PPC-32R", 2400), ("MGH-PSC-42", 600)],
            "Mugher to Addis Bole — specialty PSC for GERD contractor orders.",
        )

        # Submitted (approved, not yet dispatched)
        await make_transfer(
            "SHIP-2026-011",
            "WH-HBS-01",
            "WH-ADD-03",
            "APPROVED",
            [("HBS-PPC-32R", 2500), ("HBS-OPC-42N", 1200)],
            "Habesha to Addis Megenagna — northern Addis retail market.",
        )
        await make_transfer(
            "SHIP-2026-012",
            "WH-NAT-01",
            "WH-JIM-01",
            "APPROVED",
            [("NAT-PPC-32R", 1800)],
            "National Cement to Jimma — competitive push into Oromia west.",
        )
        await make_transfer(
            "SHIP-2026-013",
            "WH-LMI-01",
            "WH-DSS-01",
            "APPROVED",
            [("LMI-OPC-42R", 3000), ("LMI-PPC-32R", 3500)],
            "Lemi to Dessie — Amhara south corridor. Undercutting Messebo.",
        )

        # Draft / newly created
        await make_transfer(
            "SHIP-2026-014",
            "WH-DNG-01",
            "WH-BDR-01",
            "DRAFT",
            [("DNG-OPC-42R", 2500), ("DNG-3X-42N", 1000)],
            "Dangote 3X premium to Bahir Dar — GERD-area infrastructure projects.",
        )
        await make_transfer(
            "SHIP-2026-015",
            "WH-MSB-01",
            "WH-GND-01",
            "DRAFT",
            [("MSB-OPC-42R", 3000), ("MSB-RHC-52R", 500)],
            "Messebo OPC + Rapid Hardening to Gondar — fast-track road project.",
        )
        await make_transfer(
            "SHIP-2026-016",
            "WH-DRB-01",
            "WH-HWS-01",
            "DRAFT",
            [("DRB-OPC-42R", 2000), ("DRB-PPC-32R", 3000)],
            "Derba to Hawassa — SNNPR construction season. Hawassa Industrial Park.",
        )
        await make_transfer(
            "SHIP-2026-017",
            "WH-ADD-01",
            "WH-ADD-02",
            "DRAFT",
            [("DNG-OPC-42R", 800), ("MGH-OPC-42N", 700), ("LMI-PPC-32R", 1200)],
            "Intra-Addis redistribution — Central Depot to Bole for retail contractors.",
        )
        await s.commit()
        print("  Transfer orders: 17 created")

        # ── Summary ───────────────────────────────────────────────────────
        counts = {}
        for tbl in (
            "products",
            "warehouses",
            "inventory_transactions",
            "transfer_orders",
        ):
            row = (
                await s.execute(
                    text(f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = :tid"),
                    {"tid": tid},
                )
            ).scalar()
            counts[tbl] = row

        print("\n" + "=" * 55)
        print("  SEED COMPLETE — Ethiopian Cement Hub")
        print("=" * 55)
        print(f"  Products              : {counts['products']}")
        print(f"  Warehouses            : {counts['warehouses']}")
        print(f"  Inventory transactions: {counts['inventory_transactions']}")
        print(f"  Transfer orders       : {counts['transfer_orders']}")
        print("=" * 55)
        print("\nLogin credentials:")
        print("  admin@eth-cement-hub.et  /  (set via Cognito — no local password)")
        print("  Tenant slug: eth-cement-hub")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
