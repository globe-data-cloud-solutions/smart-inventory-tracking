from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Permission:
    id: str
    abac: List[str] = field(default_factory=list)


class PERMISSIONS:
    # ── Domain 1 — Tenant & System ─────────────────────────────────────────
    TENANT_CREATE           = Permission("tenant:create",           ["platform_only"])
    TENANT_VIEW             = Permission("tenant:view",             ["tenant_id"])
    TENANT_LIST             = Permission("tenant:list",             ["platform_only"])
    TENANT_CONFIGURE        = Permission("tenant:configure",        ["tenant_id"])
    TENANT_SET_ORG_TYPE     = Permission("tenant:set_org_type",     ["tenant_id", "audit_required"])
    TENANT_DEACTIVATE       = Permission("tenant:deactivate",       ["platform_only", "audit_required"])
    # Org hierarchy node and level management (SA/TA only)
    TENANT_MANAGE           = Permission("tenant:manage",           ["tenant_id", "audit_required"])
    # SA registry and activity log (platform_only — SA gets these via seed_permissions)
    TENANT_REGISTRY_VIEW    = Permission("tenant:registry_view",    ["platform_only"])
    TENANT_ACTIVITY_VIEW    = Permission("tenant:activity_view",    ["platform_only"])
    # SA contract date management (platform_only — TA cannot set contract dates)
    TENANT_CONTRACT_EDIT    = Permission("tenant:contract_edit",    ["platform_only"])
    # SA wizard re-edit of existing tenant profile fields (platform_only)
    TENANT_PROFILE_EDIT     = Permission("tenant:profile_edit",     ["platform_only"])
    # SA platform tier configuration (platform_only)
    PLATFORM_TIER_CONFIG_VIEW = Permission("platform:tier_config_view", ["platform_only"])
    PLATFORM_TIER_CONFIG_EDIT = Permission("platform:tier_config_edit", ["platform_only"])
    # Billing (S5) — SA invoice/payment management, TA read-only on its own tenant
    BILLING_VIEW             = Permission("billing:view",             ["platform_only"])
    BILLING_MANAGE           = Permission("billing:manage",           ["platform_only", "audit_required"])
    BILLING_VIEW_OWN         = Permission("billing:view_own",         ["tenant_id"])

    # ── Domain 2 — User Management ─────────────────────────────────────────
    USER_CREATE             = Permission("user:create",             ["tenant_id"])
    USER_VIEW               = Permission("user:view",               ["tenant_id"])
    USER_LIST               = Permission("user:list",               ["tenant_id"])
    USER_UPDATE             = Permission("user:update",             ["tenant_id"])
    USER_DEACTIVATE         = Permission("user:deactivate",         ["tenant_id", "audit_required"])
    USER_ASSIGN_ROLE        = Permission("user:assign_role",        ["tenant_id", "role_ceiling"])
    USER_RESET_PASSWORD     = Permission("user:reset_password",     ["tenant_id"])
    # Covers update, deactivate, reactivate, and ACTING/DELEGATE assignment management
    USER_MANAGE             = Permission("user:manage",             ["tenant_id", "role_ceiling"])

    # ── Domain 3 — Product ─────────────────────────────────────────────────
    PRODUCT_CREATE          = Permission("product:create",          ["tenant_id", "sku_cap"])
    PRODUCT_VIEW            = Permission("product:view",            ["tenant_id"])
    PRODUCT_LIST            = Permission("product:list",            ["tenant_id"])
    PRODUCT_UPDATE          = Permission("product:update",          ["tenant_id"])
    PRODUCT_DEACTIVATE      = Permission("product:deactivate",      ["tenant_id", "audit_required"])
    PRODUCT_DISCONTINUE     = Permission("product:discontinue",     ["tenant_id", "audit_required"])
    PRODUCT_REACTIVATE      = Permission("product:reactivate",      ["tenant_id"])
    PRODUCT_IMPORT_BULK     = Permission("product:import_bulk",     ["tenant_id", "sku_cap"])
    PRODUCT_SET_DISPATCH    = Permission("product:set_dispatch_strategy", ["tenant_id"])
    PRODUCT_READ_NEXT_SKU   = Permission("product:read_next_sku",   ["tenant_id"])
    PRODUCT_LIST_CATEGORIES      = Permission("product:list_categories",      ["tenant_id"])
    PRODUCT_CREATE_CATEGORY      = Permission("product:create_category",      ["tenant_id"])
    PRODUCT_LIST_BRANDS          = Permission("product:list_brands",          ["tenant_id"])
    PRODUCT_CREATE_BRAND         = Permission("product:create_brand",         ["tenant_id"])
    PRODUCT_LIST_TYPE_CODES      = Permission("product:list_type_codes",      ["tenant_id"])
    PRODUCT_CREATE_TYPE_CODE     = Permission("product:create_type_code",     ["tenant_id"])
    PRODUCT_LIST_UOMS            = Permission("product:list_uoms",            ["tenant_id"])
    PRODUCT_CREATE_UOM           = Permission("product:create_uom",           ["tenant_id"])
    PRODUCT_LIST_PACKAGING_TYPES  = Permission("product:list_packaging_types",  ["tenant_id"])
    PRODUCT_CREATE_PACKAGING_TYPE = Permission("product:create_packaging_type", ["tenant_id"])
    # Product-level approval rule overrides (PROMPT C)
    PRODUCT_VIEW_APPROVAL_RULES        = Permission("product:view_approval_rules",        ["tenant_id"])
    PRODUCT_MANAGE_APPROVAL_RULES      = Permission("product:manage_approval_rules",      ["tenant_id", "audit_required"])
    # Per-product authority floor overrides in product_approval_minimums (PROMPT 2D)
    PRODUCT_MANAGE_APPROVAL_MINIMUMS   = Permission("product:manage_approval_minimums",   ["tenant_id", "audit_required"])
    # Product image upload (TA and NM)
    PRODUCT_UPLOAD_IMAGE               = Permission("product:upload_image",               ["tenant_id"])
    # Tenant branding upload (TA only)
    TENANT_UPLOAD_BRANDING             = Permission("tenant:upload_branding",             ["tenant_id"])

    # ── Domain 4 — Inventory ───────────────────────────────────────────────
    INVENTORY_RECEIVE       = Permission("inventory:receive",       ["tenant_id", "warehouse_id"])
    INVENTORY_ADJUST        = Permission("inventory:adjust",        ["tenant_id", "warehouse_id", "approval_threshold"])
    INVENTORY_TRANSFER      = Permission("inventory:transfer",      ["tenant_id", "scope"])
    INVENTORY_CYCLE_COUNT   = Permission("inventory:cycle_count",   ["tenant_id", "warehouse_id"])
    INVENTORY_VIEW          = Permission("inventory:view",          ["tenant_id"])
    INVENTORY_VIEW_LEDGER   = Permission("inventory:view_ledger",   ["tenant_id"])
    INVENTORY_VIEW_BALANCE  = Permission("inventory:view_balance",  ["tenant_id", "warehouse_id"])
    INVENTORY_ISSUE         = Permission("inventory:issue",         ["tenant_id", "warehouse_id"])
    INVENTORY_RESERVE       = Permission("inventory:reserve",       ["tenant_id", "warehouse_id"])
    INVENTORY_RELEASE       = Permission("inventory:release_reservation", ["tenant_id", "warehouse_id"])
    INVENTORY_RETURN        = Permission("inventory:return",        ["tenant_id", "warehouse_id"])
    # IMTS §10 — hierarchical distribution view (NM/LM role, read replica)
    # Roles that may call this endpoint are enforced via role_permissions DB table.
    INVENTORY_VIEW_DISTRIBUTION      = Permission("inventory:view_distribution",      ["tenant_id", "facility_id"])
    # IMTS §10.1 — multi-source suggestion algorithm (WM/RM role, read replica)
    INVENTORY_VIEW_SUGGESTED_SOURCES = Permission("inventory:view_suggested_sources", ["tenant_id", "warehouse_id"])

    # ── Domain 5 — Warehouse ──────────────────────────────────────────────
    WAREHOUSE_CREATE        = Permission("warehouse:create",        ["tenant_id"])
    WAREHOUSE_VIEW          = Permission("warehouse:view",          ["tenant_id"])
    WAREHOUSE_LIST          = Permission("warehouse:list",          ["tenant_id"])
    WAREHOUSE_UPDATE        = Permission("warehouse:update",        ["tenant_id"])
    WAREHOUSE_DEACTIVATE    = Permission("warehouse:deactivate",    ["tenant_id", "audit_required"])

    # ── Domain 6 — Transfer Orders ────────────────────────────────────────
    TRANSFER_CREATE         = Permission("transfer:create",         ["tenant_id"])
    TRANSFER_SUBMIT         = Permission("transfer:submit",         ["tenant_id"])
    TRANSFER_APPROVE        = Permission("transfer:approve",        ["tenant_id", "region_id"])
    TRANSFER_REJECT         = Permission("transfer:reject",         ["tenant_id", "region_id"])
    TRANSFER_DISPATCH       = Permission("transfer:dispatch",       ["tenant_id", "warehouse_id"])
    TRANSFER_RECEIVE        = Permission("transfer:receive",        ["tenant_id", "warehouse_id"])
    TRANSFER_CANCEL         = Permission("transfer:cancel",         ["tenant_id"])
    TRANSFER_VIEW           = Permission("transfer:view",           ["tenant_id"])
    TRANSFER_LIST           = Permission("transfer:list",           ["tenant_id"])
    TRANSFER_RESOLVE_DISCREPANCY = Permission("transfer:resolve_discrepancy", ["tenant_id"])

    # ── Domain 7 — Adjustment Orders ──────────────────────────────────────
    ADJUSTMENT_CREATE       = Permission("adjustment:create",       ["tenant_id", "warehouse_id"])
    ADJUSTMENT_SUBMIT       = Permission("adjustment:submit",       ["tenant_id"])
    ADJUSTMENT_APPROVE      = Permission("adjustment:approve",      ["tenant_id", "approval_threshold"])
    ADJUSTMENT_REJECT       = Permission("adjustment:reject",       ["tenant_id"])
    ADJUSTMENT_APPLY        = Permission("adjustment:apply",        ["tenant_id"])
    ADJUSTMENT_CANCEL       = Permission("adjustment:cancel",       ["tenant_id"])
    ADJUSTMENT_VIEW         = Permission("adjustment:view",         ["tenant_id"])
    ADJUSTMENT_LIST         = Permission("adjustment:list",         ["tenant_id"])

    # ── Domain 8 — Order Management ───────────────────────────────────────
    ORDER_CREATE            = Permission("order:create",            ["tenant_id"])
    ORDER_VIEW              = Permission("order:view",              ["tenant_id"])
    ORDER_LIST              = Permission("order:list",              ["tenant_id"])
    ORDER_UPDATE            = Permission("order:update",            ["tenant_id"])
    ORDER_CANCEL            = Permission("order:cancel",            ["tenant_id", "audit_required"])
    ORDER_APPROVE           = Permission("order:approve",           ["tenant_id", "approval_threshold"])
    ORDER_SHIP              = Permission("order:ship",              ["tenant_id"])
    ORDER_COMPLETE          = Permission("order:complete",          ["tenant_id"])

    # ── Domain 9 — Dispatch ───────────────────────────────────────────────
    DISPATCH_CONFIGURE      = Permission("dispatch:configure",      ["tenant_id"])
    DISPATCH_FEFO_OVERRIDE  = Permission("dispatch:fefo_override",  ["tenant_id", "override_permission", "reason_required"])
    DISPATCH_VIEW_CONFIG    = Permission("dispatch:view_config",    ["tenant_id"])
    DISPATCH_LOT_SELECT     = Permission("dispatch:lot_select",     ["tenant_id", "warehouse_id"])

    # ── Domain 10 — Logistics ─────────────────────────────────────────────
    LOGISTICS_FLEET_MANAGE  = Permission("logistics:fleet_manage",  ["tenant_id"])
    LOGISTICS_ROUTE_CREATE  = Permission("logistics:route_create",  ["tenant_id"])
    LOGISTICS_ROUTE_VIEW    = Permission("logistics:route_view",    ["tenant_id"])
    LOGISTICS_DRIVER_MANAGE = Permission("logistics:driver_manage", ["tenant_id"])
    LOGISTICS_SHIPMENT_TRACK= Permission("logistics:shipment_track",["tenant_id"])

    # ── Domain 11 — AI & Analytics ───────────────────────────────────────
    AI_FORECAST_VIEW        = Permission("ai:forecast_view",        ["tenant_id"])
    AI_FORECAST_APPROVE     = Permission("ai:forecast_approve",     ["tenant_id", "audit_required"])
    AI_FORECAST_REJECT      = Permission("ai:forecast_reject",      ["tenant_id", "audit_required"])
    AI_MODEL_RUN            = Permission("ai:model_run",            ["system_only"])  # SYS ONLY
    AI_RECOMMENDATION_VIEW  = Permission("ai:recommendation_view",  ["tenant_id"])
    AI_RECOMMENDATION_APPROVE = Permission("ai:recommendation_approve", ["tenant_id", "audit_required"])
    AI_RECOMMENDATION_REJECT  = Permission("ai:recommendation_reject",  ["tenant_id", "audit_required"])
    ANALYTICS_DASHBOARD     = Permission("analytics:dashboard_view",["tenant_id"])
    ANALYTICS_REPORT_GEN    = Permission("analytics:report_generate",["tenant_id"])
    ANALYTICS_REPORT_VIEW   = Permission("analytics:report_view",   ["tenant_id"])
    ANALYTICS_EXPORT        = Permission("analytics:export",        ["tenant_id", "audit_required"])

    # ── Domain 12 — Notifications ─────────────────────────────────────────
    NOTIFICATION_VIEW       = Permission("notification:view",       ["tenant_id"])
    NOTIFICATION_CONFIGURE  = Permission("notification:configure_alerts", ["tenant_id"])
    NOTIFICATION_DISMISS    = Permission("notification:dismiss",    ["tenant_id"])

    # ── Domain 13 — Audit ─────────────────────────────────────────────────
    AUDIT_VIEW_LOGS         = Permission("audit:view_logs",         ["tenant_id"])
    AUDIT_EXPORT_LOGS       = Permission("audit:export_logs",       ["tenant_id", "audit_required"])

    # ── Domain 14 — Plans & Billing ───────────────────────────────────────
    PLAN_VIEW               = Permission("plan:view",               ["tenant_id"])
    PLAN_CHANGE             = Permission("plan:change",             ["platform_only", "audit_required"])
    PLAN_VIEW_USAGE         = Permission("plan:view_usage",         ["tenant_id"])

    # ── Domain 15 — Sync ──────────────────────────────────────────────────
    SYNC_QUEUE_VIEW         = Permission("sync:offline_queue_view", ["tenant_id"])
    SYNC_CONFLICT_RESOLVE   = Permission("sync:conflict_resolve",   ["tenant_id", "audit_required"])
    SYNC_CONFLICT_VIEW      = Permission("sync:conflict_view",      ["tenant_id"])

    # ── Domain 16 — Reports ───────────────────────────────────────────────
    REPORT_INV_VALUATION    = Permission("report:inventory_valuation",  ["tenant_id"])
    REPORT_STOCK_MOVEMENT   = Permission("report:stock_movement",       ["tenant_id"])
    REPORT_EXPIRY_ALERTS    = Permission("report:expiry_alerts",        ["tenant_id", "warehouse_id"])
    REPORT_LOW_STOCK        = Permission("report:low_stock",            ["tenant_id"])
    REPORT_LOT_TRACE        = Permission("report:lot_trace",            ["tenant_id"])
    REPORT_DISPATCH_SUMMARY = Permission("report:dispatch_summary",     ["tenant_id"])

    # ── Domain 17 — System Administration ────────────────────────────────
    SYSTEM_FEATURE_FLAG     = Permission("system:feature_flag_manage",  ["platform_only"])

    # ── Domain 18 — Positions (Session 3) ────────────────────────────────
    POSITION_VIEW          = Permission("position:view",          ["tenant_id"])
    POSITION_MANAGE        = Permission("position:manage",        ["tenant_id", "audit_required"])

    # ── Domain 19 — Transfer Type Configuration (Session 3) ──────────────
    TRANSFER_TYPE_VIEW     = Permission("transfer_type:view",     ["tenant_id"])
    TRANSFER_TYPE_MANAGE   = Permission("transfer_type:manage",   ["tenant_id", "audit_required"])

    # ── Domain 21 — Self-Approval Policies (P2/P3) ───────────────────────
    SELF_APPROVAL_POLICY_VIEW   = Permission("tenant:self_approval_view",   ["tenant_id"])
    SELF_APPROVAL_POLICY_MANAGE = Permission("tenant:self_approval_manage", ["tenant_id", "audit_required"])

    # ── Domain 20 — Transfer Approval Rules (Session 3) ──────────────────
    TRANSFER_APPROVAL_RULE_VIEW   = Permission("transfer_approval_rule:view",   ["tenant_id"])
    TRANSFER_APPROVAL_RULE_MANAGE = Permission("transfer_approval_rule:manage", ["tenant_id", "audit_required"])
    SYSTEM_PLAN_MANAGE      = Permission("system:plan_manage",          ["platform_only"])

    # ── Domain 22 — Adjustment Approval Rules (P4) ────────────────────────
    ADJUSTMENT_APPROVAL_RULE_VIEW   = Permission("adjustment_approval_rule:view",   ["tenant_id"])
    ADJUSTMENT_APPROVAL_RULE_MANAGE = Permission("adjustment_approval_rule:manage", ["tenant_id", "audit_required"])
    SYSTEM_SEED_PERMISSIONS = Permission("system:seed_permissions",     ["system_only"])
    SYSTEM_HEALTH_CHECK     = Permission("system:health_check",         [])

    # ── Domain 18 — Scanning ──────────────────────────────────────────────
    SCAN_BARCODE_LOOKUP     = Permission("scan:barcode_lookup",     ["tenant_id"])
    SCAN_BATCH_RECEIVE      = Permission("scan:batch_receive",      ["tenant_id", "warehouse_id"])

    # ── Domain 19 — Stock Count ───────────────────────────────────────────
    COUNT_CREATE_SESSION    = Permission("count:create_session",    ["tenant_id", "warehouse_id"])
    COUNT_SUBMIT            = Permission("count:submit_count",      ["tenant_id", "warehouse_id"])
    COUNT_APPROVE_VARIANCE  = Permission("count:approve_variance",  ["tenant_id", "approval_threshold"])
    COUNT_VIEW              = Permission("count:view",              ["tenant_id"])

    # ── Domain 20 — Locale / i18n ─────────────────────────────────────────
    LOCALE_VIEW             = Permission("locale:view",             [])
    LOCALE_UPDATE           = Permission("locale:update",           ["platform_only"])

    # ── Domain 21 — Role Management ───────────────────────────────────────
    ROLE_ASSIGN             = Permission("role:assign",             ["tenant_id", "role_ceiling"])
    ROLE_REVOKE             = Permission("role:revoke",             ["tenant_id", "role_ceiling"])
    ROLE_VIEW_ASSIGNMENTS   = Permission("role:view_assignments",   ["tenant_id"])

    # ── Domain 22 — Search ────────────────────────────────────────────────
    SEARCH_PRODUCTS         = Permission("search:products",         ["tenant_id"])
    SEARCH_INVENTORY        = Permission("search:inventory",        ["tenant_id"])

    # SA Operations Manual (platform_only — SA-internal doc, not for TA)
    SA_DOCS_VIEW            = Permission("sa:docs_view",            ["platform_only"])

    # ── Domain 23 — Contract Renewal (P2) ─────────────────────────────────
    TENANT_RENEWAL_REQUEST     = Permission("tenant:renewal_request",     ["tenant_id"])
    TENANT_RENEWAL_MANAGE      = Permission("tenant:renewal_manage",      ["platform_only"])
    TENANT_VIEW_CONTRACT_STATUS = Permission("tenant:view_contract_status", ["tenant_id"])

    # ── Domain 24 — Platform Contact (P4 / 080) ───────────────────────────
    PLATFORM_CONTACT_EDIT      = Permission("platform:contact_edit",      ["platform_only"])


ALL_PERMISSIONS: List[Permission] = [
    v for v in vars(PERMISSIONS).values() if isinstance(v, Permission)
]

assert len(ALL_PERMISSIONS) == 162, (
    f"Expected 162 permissions, found {len(ALL_PERMISSIONS)}. "
    "Update registry.py and re-run seed_permissions.py."
)
