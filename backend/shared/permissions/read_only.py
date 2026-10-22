"""Read-only classification — which permission actions remain usable when a
tenant's contract has gone READ_ONLY (see shared.billing.contract_stage).

Fail-closed: any action id not listed in READ_ACTIONS or
ALLOWED_WRITE_ACTIONS is treated as a write and blocked in READ_ONLY. This
is deliberate so a newly added action is blocked by default until someone
explicitly classifies it.
"""

from __future__ import annotations

READ_ACTIONS: frozenset[str] = frozenset(
    {
        "tenant:view",
        "tenant:list",
        "tenant:registry_view",
        "tenant:activity_view",
        "platform:tier_config_view",
        "billing:view",
        "billing:view_own",
        "user:view",
        "user:list",
        "product:view",
        "product:list",
        "product:read_next_sku",
        "product:list_categories",
        "product:list_brands",
        "product:list_type_codes",
        "product:list_uoms",
        "product:list_packaging_types",
        "product:view_approval_rules",
        "inventory:view",
        "inventory:view_ledger",
        "inventory:view_balance",
        "inventory:view_distribution",
        "inventory:view_suggested_sources",
        "warehouse:view",
        "warehouse:list",
        "transfer:view",
        "transfer:list",
        "adjustment:view",
        "adjustment:list",
        "order:view",
        "order:list",
        "dispatch:view_config",
        "logistics:route_view",
        "logistics:shipment_track",
        "ai:forecast_view",
        "ai:recommendation_view",
        "analytics:dashboard_view",
        "analytics:report_generate",
        "analytics:report_view",
        "analytics:export",
        "notification:view",
        "audit:view_logs",
        "audit:export_logs",
        "plan:view",
        "plan:view_usage",
        "sync:offline_queue_view",
        "sync:conflict_view",
        "report:inventory_valuation",
        "report:stock_movement",
        "report:expiry_alerts",
        "report:low_stock",
        "report:lot_trace",
        "report:dispatch_summary",
        "report:filter_options",
        "position:view",
        "transfer_type:view",
        "tenant:self_approval_view",
        "transfer_approval_rule:view",
        "adjustment_approval_rule:view",
        "system:health_check",
        "scan:barcode_lookup",
        "count:view",
        "locale:view",
        "role:view_assignments",
        "search:products",
        "search:inventory",
        "sa:docs_view",
        "tenant:view_contract_status",
    }
)

ALLOWED_WRITE_ACTIONS: frozenset[str] = frozenset(
    {
        "notification:dismiss",
        "tenant:profile_edit",
        "tenant:renewal_request",
        # Security actions stay available in READ_ONLY — a staff member must
        # still be able to get back in to view/export, and a leaver's access
        # must still be revocable, even while the tenant itself is read-only.
        "user:reset_password",
        "user:deactivate",
    }
)


def is_blocked_in_read_only(
    action_id: str,
    route_exempt: bool = False,
    force_write: bool = False,
) -> bool:
    """True if this action must be denied while a tenant is READ_ONLY.

    force_write=True skips the READ_ACTIONS/ALLOWED_WRITE_ACTIONS lookup
    entirely — the route is treated as a write regardless of the permission
    action it is decorated with (e.g. a mutating route gated behind a
    nominally read-only action id). route_exempt still wins over force_write.
    """
    if route_exempt:
        return False
    if force_write:
        return True
    if action_id in READ_ACTIONS or action_id in ALLOWED_WRITE_ACTIONS:
        return False
    return True
