"""Seed default approval rules for the demo tenants.

Inserts approval routing bands into the approval_rule table for Addis Water
(PRODUCER, addis-water) and Muger Cement (PRODUCER, muger-cement).

Rule design (from CLAUDE.md §15 + §24, Business Rule #2):
  Every stock mutation must pass through the approval workflow defined here
  before execution.  The bands are contiguous and cover all quantities
  (no gaps, no overlaps).

  PULL transfers (warehouse requests stock from upstream):
    0 – 999       → WM  (Warehouse Manager handles internally)
    1000 – 4999   → RM  (Regional Manager sign-off for mid-range)
    5000+         → NM  (National Manager for large pulls)

  PUSH transfers (upstream proactively sends stock downstream):
    0 – 4999      → NM  (NM initiates and approves all routine push)
    5000+         → TA  (Tenant Admin — CEO-equivalent per CLAUDE.md §24)

  ADJUSTMENT (damage, write-off, count variance):
    0 – 99        → WM   (minor adjustments self-approved by WM)
    100 – 999     → RM   (mid-range damage requires Regional Manager)
    1000+         → TA   (large write-offs require Tenant Admin / CEO)

  SISTER transfers (peer WH ↔ WH):
    0 – 999       → WM  (both WHs agree, no escalation)
    1000+         → RM  (RM notified and must approve larger lateral moves)

Run after `alembic upgrade head`:
  python scripts/seed_approval_rules.py

Idempotent: uses INSERT ... ON CONFLICT DO NOTHING for the tenant stub
and DELETE + re-INSERT for the rules (safe to re-run).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Add backend/ to path so `import shared` resolves
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ── Connection ──────────────────────────────────────────────────────────────

engine = create_async_engine(os.environ["DATABASE_URL"])
Session = async_sessionmaker(bind=engine, expire_on_commit=False)

# ── Tenant IDs (match seed_demo_data.py) ───────────────────────────────────

ADDIS_WATER_ID  = "10000001-0000-0000-0000-000000000001"
MUGER_CEMENT_ID = "10000002-0000-0000-0000-000000000001"

# ── Approval rule definitions ───────────────────────────────────────────────
# Each tuple: (transaction_type, min_qty, max_qty, approver_role, approval_order)
# max_qty = None means "no upper bound" (open-ended top band)

ADDIS_WATER_RULES = [
    # PULL: warehouse requests stock upstream
    ("PULL",       "0",      "999.9999",  "WM", 1),
    ("PULL",    "1000",    "4999.9999",   "RM", 1),
    ("PULL",    "5000",         None,     "NM", 1),

    # PUSH: upstream sends stock downstream
    ("PUSH",       "0",    "4999.9999",   "NM", 1),
    ("PUSH",    "5000",         None,     "TA", 1),

    # ADJUSTMENT: damage, write-off, count variance — 3 bands per CLAUDE.md §15
    ("ADJUSTMENT",    "0",   "99.9999",   "WM", 1),   # WM self-approves minor damage
    ("ADJUSTMENT",  "100",  "999.9999",   "RM", 1),   # RM approval for mid-range
    ("ADJUSTMENT", "1000",       None,    "TA", 1),   # TA (CEO) for large write-offs

    # SISTER: peer WH ↔ WH lateral transfer
    ("SISTER",     "0",     "999.9999",   "WM", 1),
    ("SISTER",  "1000",         None,     "RM", 1),
]

# Muger Cement uses the same bands (both are PRODUCER, same org size)
MUGER_CEMENT_RULES = [
    ("PULL",          "0",   "999.9999",  "WM", 1),
    ("PULL",       "1000",  "4999.9999",  "RM", 1),
    ("PULL",       "5000",       None,    "NM", 1),
    ("PUSH",          "0",  "4999.9999",  "NM", 1),
    ("PUSH",       "5000",       None,    "TA", 1),
    ("ADJUSTMENT",    "0",   "99.9999",   "WM", 1),
    ("ADJUSTMENT",  "100",  "999.9999",   "RM", 1),
    ("ADJUSTMENT", "1000",       None,    "TA", 1),
    ("SISTER",        "0",  "999.9999",   "WM", 1),
    ("SISTER",     "1000",       None,    "RM", 1),
]

SEED_DATA: list[tuple[str, list]] = [
    (ADDIS_WATER_ID,  ADDIS_WATER_RULES),
    (MUGER_CEMENT_ID, MUGER_CEMENT_RULES),
]

TENANT_STUBS = [
    {
        "id":                ADDIS_WATER_ID,
        "name":              "Addis Water",
        "organisation_type": "PRODUCER",
    },
    {
        "id":                MUGER_CEMENT_ID,
        "name":              "Muger Cement",
        "organisation_type": "PRODUCER",
    },
]

# ── Seed logic ──────────────────────────────────────────────────────────────

async def seed() -> None:
    async with Session() as session:

        # 1. Ensure tenant rows exist (won't overwrite if already seeded by seed_demo_data.py)
        for stub in TENANT_STUBS:
            await session.execute(
                text("""
                    INSERT INTO tenants
                        (id, name, organisation_type, plan_id,
                         feature_flags, approval_thresholds,
                         onboarding_complete, is_active)
                    VALUES
                        (:id, :name, :org_type, :plan_id,
                         '{}', '{}',
                         false, true)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id":       stub["id"],
                    "name":     stub["name"],
                    "org_type": stub["organisation_type"],
                    "plan_id":  str(uuid.uuid4()),
                },
            )
        print("Tenants: ensured (ON CONFLICT DO NOTHING)")

        # 2. Clear existing rules for each tenant (idempotent re-seeding)
        for tenant_id, _ in SEED_DATA:
            result = await session.execute(
                text("DELETE FROM approval_rule WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            deleted = result.rowcount
            if deleted:
                print(f"  Cleared {deleted} existing rules for tenant {tenant_id[:8]}…")

        # 3. Insert rules
        total = 0
        for tenant_id, rules in SEED_DATA:
            for (tx_type, min_qty, max_qty, role, order) in rules:
                await session.execute(
                    text("""
                        INSERT INTO approval_rule
                            (tenant_id, transaction_type,
                             min_quantity, max_quantity,
                             approver_role, approval_order,
                             is_active)
                        VALUES
                            (:tid, :tx_type,
                             :min_qty, :max_qty,
                             :role, :order,
                             true)
                    """),
                    {
                        "tid":     tenant_id,
                        "tx_type": tx_type,
                        "min_qty": min_qty,
                        "max_qty": max_qty,
                        "role":    role,
                        "order":   order,
                    },
                )
                total += 1

        await session.commit()
        print(f"\nInserted {total} approval rules across {len(SEED_DATA)} tenants.")
        print()

        # 4. Print summary
        rows = await session.execute(
            text("""
                SELECT t.name AS tenant, r.transaction_type, r.min_quantity,
                       r.max_quantity, r.approver_role
                FROM approval_rule r
                JOIN tenants t ON t.id = r.tenant_id
                ORDER BY t.name, r.transaction_type, r.min_quantity NULLS FIRST
            """),
        )
        current_tenant = None
        for row in rows:
            if row.tenant != current_tenant:
                print(f"Tenant: {row.tenant}")
                print(f"  {'Type':<12} {'Min Qty':>10} {'Max Qty':>10}  {'Approver'}")
                print(f"  {'-'*12} {'-'*10} {'-'*10}  {'-'*8}")
                current_tenant = row.tenant
            max_str = str(row.max_quantity) if row.max_quantity is not None else "unlimited"
            print(f"  {row.transaction_type:<12} {str(row.min_quantity):>10} {max_str:>10}  {row.approver_role}")
        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
