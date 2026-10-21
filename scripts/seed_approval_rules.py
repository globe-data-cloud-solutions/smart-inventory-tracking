"""Seed default approval rules for the demo tenants.

Inserts approval routing bands into the approval_rule table for Addis Water
(PRODUCER, addis-water) and Muger Cement (PRODUCER, muger-cement).

Rule design (from CLAUDE.md §15 + §24, PRD-APPENDIX §B9, Business Rule #2):
  Every stock mutation must pass through the approval workflow defined here
  before execution.  The bands are contiguous and cover all quantities
  (no gaps, no overlaps).

  PULL / PUSH transfers:
    0 – 99        → WM  level 4  (routine ops, warehouse self-manages)
    100 – 999     → RM  level 2  (regional sign-off for mid-range)
    1000+         → NM  level 1  (national manager for large moves)

  SISTER transfers (peer WH ↔ WH):
    Same bands as PULL — PRD-APPENDIX §B9.
    Migration 029 syncs authority fields from matching PULL rows automatically.

  ADJUSTMENT (damage, write-off, count variance):
    0 – 99        → WM  level 4  auto_approve=true  (minor damage self-certified)
    100 – 999     → RM  level 2  (mid-range damage requires Regional Manager)
    1000+         → TA  level 1  (large write-offs require Tenant Admin / CEO)

  RECEIVE / ISSUE:
    0 – 199       → WM  level 4  (WM handles routine receipts and issues)
    200+          → RM  level 2  (RM review for larger quantities)

  authority_level:  SA/TA/NM=1, RM=2, LM=3, WM=4
  auto_approve:     true = band approves without manual action; higher levels notified
  notify_levels:    integer array of authority levels to notify on approval/rejection

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

ADDIS_WATER_ID = "10000001-0000-0000-0000-000000000001"
MUGER_CEMENT_ID = "10000002-0000-0000-0000-000000000001"

# ── Approval rule definitions ───────────────────────────────────────────────
# Each tuple:
#   (transaction_type, min_qty, max_qty,
#    approver_role, approval_order,
#    authority_level, auto_approve, notify_levels)
#
# max_qty    = None  →  no upper bound (open-ended top band)
# notify_levels      →  PostgreSQL array literal string, e.g. "'{1,2}'" or "'{}'"

ADDIS_WATER_RULES = [
    # ── PULL ───────────────────────────────────────────────────────────────
    ("PULL", "0", "99.9999", "WM", 1, 4, False, "'{}'"),
    ("PULL", "100", "999.9999", "RM", 1, 2, False, "'{1}'"),
    ("PULL", "1000", None, "NM", 1, 1, False, "'{}'"),
    # ── PUSH ───────────────────────────────────────────────────────────────
    ("PUSH", "0", "99.9999", "WM", 1, 4, False, "'{}'"),
    ("PUSH", "100", "999.9999", "RM", 1, 2, False, "'{1}'"),
    ("PUSH", "1000", None, "NM", 1, 1, False, "'{}'"),
    # ── SISTER (migration 029 will sync authority fields from PULL) ────────
    ("SISTER", "0", "99.9999", "WM", 1, 4, False, "'{}'"),
    ("SISTER", "100", "999.9999", "RM", 1, 2, False, "'{1}'"),
    ("SISTER", "1000", None, "NM", 1, 1, False, "'{}'"),
    # ── ADJUSTMENT ─────────────────────────────────────────────────────────
    ("ADJUSTMENT", "0", "99.9999", "WM", 1, 4, True, "'{}'"),  # auto-approved
    ("ADJUSTMENT", "100", "999.9999", "RM", 1, 2, False, "'{1}'"),
    ("ADJUSTMENT", "1000", None, "TA", 1, 1, False, "'{}'"),
    # ── RECEIVE ────────────────────────────────────────────────────────────
    ("RECEIVE", "0", "199.9999", "WM", 1, 4, False, "'{}'"),
    ("RECEIVE", "200", None, "RM", 1, 2, False, "'{1}'"),
    # ── ISSUE ──────────────────────────────────────────────────────────────
    ("ISSUE", "0", "199.9999", "WM", 1, 4, False, "'{}'"),
    ("ISSUE", "200", None, "RM", 1, 2, False, "'{1}'"),
]

# Muger Cement — same org type and size, identical bands
MUGER_CEMENT_RULES = [
    ("PULL", "0", "99.9999", "WM", 1, 4, False, "'{}'"),
    ("PULL", "100", "999.9999", "RM", 1, 2, False, "'{1}'"),
    ("PULL", "1000", None, "NM", 1, 1, False, "'{}'"),
    ("PUSH", "0", "99.9999", "WM", 1, 4, False, "'{}'"),
    ("PUSH", "100", "999.9999", "RM", 1, 2, False, "'{1}'"),
    ("PUSH", "1000", None, "NM", 1, 1, False, "'{}'"),
    ("SISTER", "0", "99.9999", "WM", 1, 4, False, "'{}'"),
    ("SISTER", "100", "999.9999", "RM", 1, 2, False, "'{1}'"),
    ("SISTER", "1000", None, "NM", 1, 1, False, "'{}'"),
    ("ADJUSTMENT", "0", "99.9999", "WM", 1, 4, True, "'{}'"),
    ("ADJUSTMENT", "100", "999.9999", "RM", 1, 2, False, "'{1}'"),
    ("ADJUSTMENT", "1000", None, "TA", 1, 1, False, "'{}'"),
    ("RECEIVE", "0", "199.9999", "WM", 1, 4, False, "'{}'"),
    ("RECEIVE", "200", None, "RM", 1, 2, False, "'{1}'"),
    ("ISSUE", "0", "199.9999", "WM", 1, 4, False, "'{}'"),
    ("ISSUE", "200", None, "RM", 1, 2, False, "'{1}'"),
]

SEED_DATA: list[tuple[str, list]] = [
    (ADDIS_WATER_ID, ADDIS_WATER_RULES),
    (MUGER_CEMENT_ID, MUGER_CEMENT_RULES),
]

TENANT_STUBS = [
    {
        "id": ADDIS_WATER_ID,
        "name": "Addis Water",
        "organisation_type": "PRODUCER",
    },
    {
        "id": MUGER_CEMENT_ID,
        "name": "Muger Cement",
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
                    "id": stub["id"],
                    "name": stub["name"],
                    "org_type": stub["organisation_type"],
                    "plan_id": str(uuid.uuid4()),
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
            for (
                tx_type,
                min_qty,
                max_qty,
                role,
                order,
                auth_level,
                auto_approve,
                notify_levels,
            ) in rules:
                await session.execute(
                    text(f"""
                        INSERT INTO approval_rule
                            (tenant_id, transaction_type,
                             min_quantity, max_quantity,
                             approver_role, approval_order,
                             authority_level, auto_approve,
                             notify_levels,
                             is_active)
                        VALUES
                            (:tid, :tx_type,
                             :min_qty, :max_qty,
                             :role, :order,
                             :auth_level, :auto_approve,
                             {notify_levels}::integer[],
                             true)
                    """),
                    {
                        "tid": tenant_id,
                        "tx_type": tx_type,
                        "min_qty": min_qty,
                        "max_qty": max_qty,
                        "role": role,
                        "order": order,
                        "auth_level": auth_level,
                        "auto_approve": auto_approve,
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
                       r.max_quantity, r.approver_role, r.authority_level,
                       r.auto_approve, r.notify_levels
                FROM approval_rule r
                JOIN tenants t ON t.id = r.tenant_id
                ORDER BY t.name, r.transaction_type, r.min_quantity NULLS FIRST
            """),
        )
        current_tenant = None
        for row in rows:
            if row.tenant != current_tenant:
                print(f"Tenant: {row.tenant}")
                print(
                    f"  {'Type':<12} {'Min':>8} {'Max':>10}  {'Role':<4}  {'Lvl':>3}  {'Auto':>5}  Notify"
                )
                print(
                    f"  {'-' * 12} {'-' * 8} {'-' * 10}  {'-' * 4}  {'-' * 3}  {'-' * 5}  {'-' * 8}"
                )
                current_tenant = row.tenant
            max_str = (
                str(row.max_quantity) if row.max_quantity is not None else "unlimited"
            )
            auto_str = "yes" if row.auto_approve else "no"
            notify_str = str(row.notify_levels) if row.notify_levels else "[]"
            print(
                f"  {row.transaction_type:<12} {str(row.min_quantity):>8} {max_str:>10}"
                f"  {row.approver_role:<4}  {row.authority_level:>3}  {auto_str:>5}  {notify_str}"
            )
        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
