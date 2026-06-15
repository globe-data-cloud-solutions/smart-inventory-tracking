"""Seed all 115 actions from registry.py into the role_permissions table.
Run after every Alembic upgrade when new permissions are added.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Add backend/ to path so `import shared` works (shared package == backend/shared/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared.permissions.registry import ALL_PERMISSIONS

ROLE_PERMISSION_MATRIX: dict[str, dict[str, str]] = {
    # grant_type: FULL | CONDITIONAL | READ_ONLY
    "SA": {p.id: "FULL" for p in ALL_PERMISSIONS},  # SA gets everything
    "TA": {
        "tenant:configure": "FULL", "tenant:view": "FULL", "tenant:manage": "FULL",
        "transfer_type:view": "FULL",
        "user:create": "FULL", "user:view": "FULL", "user:list": "FULL",
        "user:update": "FULL", "user:manage": "FULL", "user:deactivate": "FULL",
        "user:assign_role": "FULL", "user:reset_password": "FULL",
        "product:create": "FULL", "product:view": "FULL", "product:list": "FULL",
        "product:update": "FULL", "product:import_bulk": "FULL",
        "product:read_next_sku": "FULL",
        "product:manage_approval_minimums": "FULL",
        "inventory:receive": "FULL", "inventory:adjust": "CONDITIONAL",
        "inventory:transfer": "FULL", "inventory:cycle_count": "FULL",
        "inventory:view": "FULL", "inventory:view_ledger": "FULL",
        "inventory:view_balance": "FULL",
        "transfer:create": "FULL", "transfer:submit": "FULL", "transfer:approve": "FULL",
        "transfer:reject": "FULL", "transfer:view": "FULL", "transfer:list": "FULL",
        "adjustment:create": "FULL", "adjustment:approve": "FULL",
        "adjustment:view": "FULL", "adjustment:list": "FULL",
        "dispatch:configure": "FULL", "dispatch:view_config": "FULL",
        "audit:view_logs": "FULL", "audit:export_logs": "FULL",
        "report:inventory_valuation": "FULL", "report:stock_movement": "FULL",
        "report:expiry_alerts": "FULL", "report:low_stock": "FULL",
        "notification:view": "FULL", "notification:configure_alerts": "FULL",
        "plan:view": "FULL", "plan:view_usage": "FULL",
        "role:assign": "FULL", "role:revoke": "FULL", "role:view_assignments": "FULL",
        "search:products": "FULL", "search:inventory": "FULL",
        "ai:forecast_view": "FULL", "analytics:dashboard_view": "FULL",
        "locale:view": "FULL",
    },
    "NM": {
        "product:create": "FULL", "product:view": "FULL", "product:list": "FULL",
        "product:update": "FULL", "product:set_dispatch_strategy": "FULL",
        "product:read_next_sku": "FULL",
        "inventory:receive": "FULL", "inventory:adjust": "CONDITIONAL",
        "inventory:transfer": "FULL", "inventory:view": "FULL",
        "inventory:view_ledger": "FULL", "inventory:view_balance": "FULL",
        "inventory:issue": "FULL",
        "transfer:create": "FULL", "transfer:submit": "FULL", "transfer:approve": "FULL",
        "transfer:reject": "FULL", "transfer:dispatch": "FULL",
        "transfer:view": "FULL", "transfer:list": "FULL",
        "adjustment:create": "FULL", "adjustment:submit": "FULL", "adjustment:approve": "FULL",
        "adjustment:view": "FULL", "adjustment:list": "FULL",
        "dispatch:configure": "FULL", "dispatch:view_config": "FULL", "transfer_type:view": "FULL",
        "order:create": "FULL", "order:view": "FULL", "order:list": "FULL",
        "order:approve": "FULL",
        "report:inventory_valuation": "FULL", "report:stock_movement": "FULL",
        "report:expiry_alerts": "FULL", "report:low_stock": "FULL",
        "report:lot_trace": "FULL", "report:dispatch_summary": "FULL",
        "ai:forecast_view": "FULL", "ai:forecast_approve": "FULL",
        "analytics:dashboard_view": "FULL", "analytics:report_view": "FULL",
        "notification:view": "FULL", "search:products": "FULL", "search:inventory": "FULL",
        "locale:view": "FULL", "position:view": "FULL",
    },
    "RM": {
        "product:list": "FULL", "product:view": "FULL",
        "inventory:receive": "FULL", "inventory:adjust": "CONDITIONAL",
        "inventory:transfer": "FULL", "inventory:cycle_count": "FULL",
        "inventory:view": "FULL", "inventory:view_ledger": "FULL",
        "inventory:view_balance": "FULL", "inventory:issue": "FULL",
        "transfer:create": "FULL", "transfer:submit": "FULL", "transfer:approve": "FULL",
        "transfer:reject": "FULL", "transfer:dispatch": "FULL",
        "transfer:receive": "FULL", "transfer:cancel": "FULL",
        "transfer:view": "FULL", "transfer:list": "FULL",
        "adjustment:create": "FULL", "adjustment:submit": "FULL",
        "adjustment:approve": "FULL", "adjustment:view": "FULL", "adjustment:list": "FULL",
        "order:view": "FULL", "order:list": "FULL", "order:approve": "FULL",
        "dispatch:configure": "FULL", "dispatch:view_config": "FULL", "transfer_type:view": "FULL",
        "dispatch:fefo_override": "CONDITIONAL",
        "report:low_stock": "FULL", "report:expiry_alerts": "FULL",
        "report:stock_movement": "FULL", "report:dispatch_summary": "FULL",
        "count:create_session": "FULL", "count:approve_variance": "FULL", "count:view": "FULL",
        "notification:view": "FULL", "search:products": "FULL", "search:inventory": "FULL",
        "locale:view": "FULL", "position:view": "FULL",
        "tenant:self_approval_view": "FULL", "adjustment_approval_rule:view": "FULL",
        "transfer_approval_rule:view": "FULL",
    },
    "WM": {
        "product:list": "FULL", "product:view": "FULL",
        "inventory:receive": "FULL", "inventory:adjust": "CONDITIONAL",
        "inventory:transfer": "FULL", "inventory:cycle_count": "FULL",
        "inventory:view": "FULL", "inventory:view_balance": "FULL",
        "inventory:issue": "FULL", "inventory:reserve": "FULL",
        "inventory:release_reservation": "FULL", "inventory:return": "FULL",
        "transfer:create": "FULL", "transfer:submit": "FULL",
        "transfer:dispatch": "FULL", "transfer:receive": "FULL",
        "transfer:view": "FULL", "transfer:list": "FULL",
        "adjustment:create": "FULL", "adjustment:submit": "FULL",
        "adjustment:view": "FULL", "adjustment:list": "FULL",
        "count:create_session": "FULL", "count:submit_count": "FULL", "count:view": "FULL",
        "dispatch:view_config": "FULL", "dispatch:lot_select": "FULL", "transfer_type:view": "FULL",
        "scan:barcode_lookup": "FULL", "scan:batch_receive": "FULL",
        "report:low_stock": "FULL", "report:expiry_alerts": "FULL",
        "notification:view": "FULL", "search:products": "FULL", "search:inventory": "FULL",
        "sync:offline_queue_view": "FULL", "sync:conflict_view": "FULL",
        "locale:view": "FULL", "position:view": "FULL",
        "tenant:self_approval_view": "FULL", "adjustment_approval_rule:view": "FULL",
        "transfer_approval_rule:view": "FULL",
    },
    "LM": {
        "product:list": "FULL", "product:view": "FULL",
        "logistics:fleet_manage": "FULL", "logistics:route_create": "FULL",
        "logistics:route_view": "FULL", "logistics:driver_manage": "FULL",
        "logistics:shipment_track": "FULL",
        "order:ship": "FULL", "order:view": "FULL", "order:list": "FULL",
        "transfer:dispatch": "FULL", "transfer:view": "FULL", "transfer_type:view": "FULL",
        "inventory:view_balance": "READ_ONLY", "notification:view": "FULL",
        "locale:view": "FULL", "position:view": "FULL",
        "tenant:self_approval_view": "FULL", "adjustment_approval_rule:view": "FULL",
        "transfer_approval_rule:view": "FULL",
    },
    "SA_GT": {
        "scan:barcode_lookup": "FULL", "scan:batch_receive": "FULL",
        "inventory:receive": "FULL", "inventory:issue": "FULL",
        "inventory:view_balance": "READ_ONLY",
        "sync:offline_queue_view": "FULL",
        "notification:view": "FULL", "locale:view": "FULL", "position:view": "FULL",
    },
    "RT": {
        "inventory:view_balance": "READ_ONLY",
        "report:low_stock": "READ_ONLY",
        "scan:barcode_lookup": "FULL",
        "notification:view": "FULL", "locale:view": "FULL", "position:view": "FULL",
    },
    "AU": {
        "audit:view_logs": "FULL", "audit:export_logs": "FULL",
        "report:inventory_valuation": "READ_ONLY",
        "report:stock_movement": "READ_ONLY",
        "report:expiry_alerts": "READ_ONLY",
        "report:low_stock": "READ_ONLY",
        "report:lot_trace": "READ_ONLY",
        "report:dispatch_summary": "READ_ONLY",
        "inventory:view_ledger": "READ_ONLY",
        "analytics:report_view": "READ_ONLY",
        "locale:view": "FULL", "position:view": "FULL",
    },
    "SYS": {
        "ai:model_run": "FULL",
        "system:seed_permissions": "FULL",
        "system:health_check": "FULL",
        "system:feature_flag_manage": "FULL",
        "system:plan_manage": "FULL",
    },
}


async def seed() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with Session() as session:
        inserted = 0
        for role, permissions in ROLE_PERMISSION_MATRIX.items():
            for action_id, grant_type in permissions.items():
                result = await session.execute(
                    text(
                        "INSERT INTO role_permissions (role_code, action_id, grant_type) "
                        "VALUES (:role, :action, :grant) "
                        "ON CONFLICT (role_code, action_id) DO UPDATE "
                        "SET grant_type = EXCLUDED.grant_type, is_active = true"
                    ),
                    {"role": role, "action": action_id, "grant": grant_type},
                )
                inserted += result.rowcount
        await session.commit()
        print(f"Seeded {inserted} role-permission grants across {len(ROLE_PERMISSION_MATRIX)} roles.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
