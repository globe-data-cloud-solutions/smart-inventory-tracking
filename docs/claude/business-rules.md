## 24. Business Rules — Enforced by Code

PRs that violate these rules do not merge.

```
1.  Stock balance never goes below zero without override permission + audit log entry.
2.  Every stock mutation is an INSERT into inventory_transactions — never a direct balance UPDATE.
3.  Every ledger transaction has a unique idempotency key.
4.  FEFO is automatically enforced when batch_tracking=True AND expiry_date is populated on the product.
5.  FEFO override requires: dispatch:fefo_override permission + reason_code + DispatchOverrideLog INSERT.
6.  Outbox row is written in the SAME database transaction as the primary ledger record.
7.  Celery task handlers check whether the outbox row is PROCESSING or PROCESSED before doing any work.
8.  AI recommendations always start with status=PENDING_APPROVAL and never auto-execute.
9.  ai:model_run (Action 91) is SYS role only — any user role call returns HTTP 403.
10. State machine raises InvalidStateTransitionError (HTTP 422) on any invalid transition.
11. Users cannot assign roles at or above their own level in the hierarchy.
12. Cross-tenant data access is blocked by PostgreSQL RLS for all roles except SA in support context.
13. audit_logs table has CREATE RULE preventing UPDATE or DELETE — these rules must never be removed.
14. Permission enforcement runs at all three layers: gateway + service + PostgreSQL RLS.
15. organisation_type changes are audit-logged with before-value, after-value, user, and timestamp.
16. SKU plan caps are enforced at the API gateway — never inside service business logic.
17. Analytics queries use DATABASE_READ_URL (read replica) — never the primary DATABASE_URL.
18. parent_tenant_id column exists on the tenants table — never drop this column.
19. Every new route has @require_permission — enforced by scripts/ci_drift_check.py in CI.
20. All UI strings use i18n keys — no hardcoded English text in JSX or HTML templates.
21. The site is served over HTTPS — required for iOS camera access for barcode scanning.
22. Apache Kafka, RabbitMQ, and aiokafka are not used anywhere in this codebase.
23. No external ERP system integration is implemented or referenced in code.
24. Split-request legs (parent_transfer_id IS NOT NULL) each carry their own idempotency key
    and run their own type-specific state machine. The parent record status is read-only —
    it is derived from the aggregate state of all legs and never set directly by application code.
25. A user's warehouse_id JWT claim maps to organization_node.id regardless of hierarchy level.
    For roles in FACILITY_SCOPED_ROLES (WM, LM, SA_GT, RT), warehouse-scope ABAC checks grant
    access to the assigned node AND all active descendant nodes, resolved via recursive CTE on
    organization_node.parent_node_id. This traversal is implemented in
    backend/shared/permissions/hierarchy_service.py (get_descendant_node_ids()) and wired into
    check_permission() in middleware.py. Authority is never inferred from role alone and never
    assumed from org_node_hierarchy (that table is used for supply network topology, not scope
    resolution). LM Track B (no node assigned, warehouse_id=None in JWT) bypasses this check
    entirely and has tenant-wide visibility (NO_NODE_TENANT_WIDE_ROLES in hierarchy_service.py,
    decided by Alex 2026-10-22). Every other FACILITY_SCOPED_ROLE with no node fails closed.
26. warehouse_stock is a computed read model. Application code never issues
    UPDATE warehouse_stock SET … directly. The only permitted writer is update_running_balance()
    inside ledger_repo.py, called within the same DB transaction as the ledger INSERT.
    The PostgreSQL RULE on warehouse_stock enforces this at the database level.
27. DIRPUSH does not exist as a named transaction type, endpoint, or permission registry entry.
    Direct push from a higher facility to a sub-facility bypassing intermediate levels is
    modelled as a standard PUSH transaction whose SUPPLY_FROM relationship in org_node_hierarchy
    spans non-adjacent hierarchy levels. No separate code path exists or is permitted.
```

### IMTS role mapping — canonical codes used in all code and permission checks

The IMTS design document uses different role labels from the canonical role codes in the permission registry. Developers must use canonical codes in all code; IMTS labels appear only in external documentation.

| IMTS label | Canonical code | Privilege level | Notes |
|---|---|---|---|
| Warehouse Manager (WH-M) | `WM` | 6 | Direct match |
| Regional Manager (RM) | `RM` | 7 | Direct match |
| Logistics Manager (LM) | `LM` | 6 | Direct match — same level as WM |
| General Manager (GM) | `NM` | 8 | NM (National Manager) is the correct code |
| CEO / Director | `TA` | 9 | Tenant Admin is the highest tenant-scoped role; CEO-level write-off approvals use TA |
| System Admin | `SA` or `TA` | 10 / 9 | Platform config = `SA`; tenant config = `TA` |

IMTS roles not present in IMTS but required by PRD v4: Sales Agent (`SA_GT`), Retailer (`RT`), Auditor (`AU`), SYS — these are absent from IMTS approval matrices because IMTS covers the transfer workflow domain only. Their absence in IMTS is correct and intentional.


## 28. Org Hierarchy Configuration

Full design: PRD-APPENDIX.md §B. This section states the rules that apply to all code in the hierarchy domain.

### Hierarchy Rules

```
Maximum 5 levels per tenant (Level 0–4 in tenant_hierarchy_config).
Level names, role mappings, and display labels are tenant-configurable
  — stored in tenant_hierarchy_config, not hardcoded.
Multiple root nodes are allowed (e.g. two separate factories under one tenant).
Every organization_node has is_stock_holding BOOLEAN.
  is_stock_holding=false nodes participate in the approval chain only —
  they hold no inventory, appear in no balance queries, and cannot be a
  PULL/PUSH/SISTER source or destination. Enforced (2026-10-26) in
  InventoryService: create_transfer (either side), receive (goods receipt)
  and create_adjustment refuse them with 422 NODE_NOT_STOCK_HOLDING. With
  no way in, such a node never has stock to issue or dispatch. Acting on
  behalf of a stock node is separate work (parked).
SISTER is a lateral transfer between two nodes at the SAME level that are
  not under each other, e.g. Factory A -> Factory B (both level 1, separate
  roots). Different levels -> 422 SISTER_LEVEL_MISMATCH. Same level already
  implies neither node is the other's ancestor.
Stock at a node is at the disposal of that node's holder only (Alex, 2026-10-26):
  Transfer issue/dispatch: TA/SA, or the holder of the source node (any role).
  Transfer receive: TA/SA, or the holder of the destination node (any role).
  Goods receipt and stock issue: the caller's own node only (TA/SA excepted),
    403 NOT_YOUR_NODE (_require_own_node in inventory_service.py). These routes
    carry the node in the body, which the permission layer does not scope.
  NM is not tenant-wide for any of these; an NM never issues or dispatches
  another node's stock. The TA completes a movement whose node has no holder.
  The transfers list buttons (getAvailableActions) follow the same rule.
Approval is different: a request stuck at a node's approval step moves to the
  next higher position in the chain, which approves on that node's behalf, with
  the TA as the last stop (SLA escalation, shared/approvals/sla_escalation.py).
  This covers approval only, never issue, dispatch or receive.
Default approver when no TA rule matches (2026-10-26): walk up parent_node_id
  from the requesting node (destination for PULL/SISTER, source for PUSH),
  approval-only nodes included. The first node above with an active PRIMARY
  holder whose role holds transfer:approve gets the step (ANY mode, every such
  holder at that node). The creator is skipped. Nobody found -> any NM -> TA.
  (approval_service._hierarchy_walk_approvers)
A rule step saved without a position defaults to the next higher level: the
  same walk, from the previous step's node (first step: the requesting node),
  TA last. The rule editor warns on such steps; saving is still allowed.
Authority scope is always resolved via get_descendant_node_ids()
  (organization_node.parent_node_id) — never inferred from role code alone (§24 Rule 25).
```

### Product Scoping Rules

```
Standard products (source_factory_id IS NULL):
  Pullable from any node in the tenant that has available stock.
  No source restriction applies.

Factory-specific products (source_factory_id IS NOT NULL):
  Pullable only from nodes within the home factory's subtree.
  Backend validates source on every PULL creation.
  Invalid source raises HTTP 422 with code INVALID_SOURCE_FACTORY.
  Frontend filters source dropdown to nodes within the factory subtree.
  Product card displays badge: "Source: [Factory Name] only".

NEVER allow a factory-specific product to be pulled from outside its
  home factory subtree. This applies to all three transfer types
  (PULL, PUSH, SISTER) and to the dispatch engine's lot selection.
```

### Personnel Assignment Rules

```
Every user has exactly ONE PRIMARY facility assignment (permanent).
ACTING assignments are time-bounded (valid_from / valid_until).
  Any manager may create ACTING for any user within their authority scope.
  No higher-level approval is required.
DELEGATE assignments are time-bounded and permission-scoped.
  Scope is explicitly defined per assignment, not inherited from role.

JWT warehouse_id always equals the user's PRIMARY facility.
  ACTING/DELEGATE facilities do not appear in the JWT.
  ABAC permission checks union all currently-active assignments.
  Expired assignments (valid_until in the past) are ignored by all checks.

User deactivation sets is_active=false on the users table and closes
  all active ACTING/DELEGATE assignments.
NEVER hard-delete a user record. Deactivation is always reversible.
NEVER allow a manager to assign a role at or above their own level.
  This rule applies to PRIMARY, ACTING, and DELEGATE assignment types.
```

### NEVER Rules (addendum to §1)

```
NEVER delete a user record — set is_active=false. Reactivation restores
  the account. Deletion would break foreign key references in audit_logs,
  inventory_transactions, and approval_history.

NEVER allow a factory-specific product's PULL to source stock from outside
  its home factory subtree. The constraint must be enforced at the service
  layer on every transfer creation — it cannot be a frontend-only guard.

NEVER hardcode level names, role display labels, or level-to-role mappings
  in application code. All such labels must be read from
  tenant_hierarchy_config at runtime and included in API responses.
  Hardcoded labels produce incorrect UX for every tenant that uses
  non-default naming (e.g. "General Manager" vs "National Manager").
```

