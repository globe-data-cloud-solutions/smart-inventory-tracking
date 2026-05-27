# SMART Platform — PRD Appendix
> Extension to the original PRD v4.0  
> Documents design decisions made during development sessions (May 2026)  
> Read alongside CLAUDE.md

---

## §A — UI/UX Design Decisions

### A1 — Inventory Balance Columns

Standard WMS Option A column layout confirmed:

| Column | Definition | Changes when |
|---|---|---|
| On Hand | Physical stock in the warehouse | APPROVED (TRANSFER_OUT debits source) |
| Reserved | Soft hold against pending outbound transfers | PENDING_APPROVAL only |
| In Transit Out | Dispatched from this WH, not yet received | ISSUED → IN_TRANSIT |
| In Transit In | Inbound to this WH, not yet received | Destination: ISSUED → IN_TRANSIT |
| Available | On Hand − Reserved − In Transit Out | Derived, never stored |

**Column timing rules — outbound transfer lifecycle (qty = 100):**

| Transfer Status | On Hand | Reserved | In Transit Out | Available |
|---|---|---|---|---|
| PENDING_APPROVAL | 2000 | 100 | 0 | 1900 |
| APPROVED | 1900 | 0 | 0 | 1900 |
| ISSUED | 1900 | 0 | 100 | 1900 |
| IN_TRANSIT | 1900 | 0 | 100 | 1900 |
| RECEIVED (source) | 1900 | 0 | 0 | 1900 |
| RECEIVED (dest) | +100 | 0 | 0 | +100 |

Key rule: In Transit Out is **informational only** — it does NOT further reduce Available once APPROVED, because On Hand was already reduced by the TRANSFER_OUT ledger entry at APPROVED.

---

### A2 — Transfer Action Matrix

Who sees which action button at each transfer status:

| Transfer Type | Status | Source WM sees | Dest WM sees | RM/NM/TA sees |
|---|---|---|---|---|
| PULL | DRAFT | — | Submit for Review, Cancel | — |
| PULL | PENDING_REVIEW | — | — | Send for Approval, Reject, Cancel |
| PULL | PENDING_APPROVAL | — | — | Approve, Reject, Cancel |
| PULL | APPROVED | Issue Stock, Cancel | — | Issue Stock, Cancel |
| PUSH | APPROVED | Advise, Issue Stock, Cancel | — | Advise, Issue Stock, Cancel |
| PUSH | ADVISED | Issue Stock, Cancel | — | Issue Stock, Cancel |
| ALL | ISSUED | Dispatch | — | Dispatch |
| ALL | IN_TRANSIT | — | Partial Receive, Mark Received | — |
| ALL | PARTIALLY_RECEIVED | — | Mark Received | — |
| ALL | RECEIVED | — | Complete Transfer | — |

**Facility scope rules:**
- Sub-WH Warehouse Managers: PULL and SISTER only (cannot initiate PUSH)
- Regional/Main WH Managers: PULL, PUSH, and SISTER
- Any WM sees action buttons ONLY for transfers involving their assigned facility
- UUID comparison must use `.toLowerCase()` on both sides (see CLAUDE.md §27)

---

### A3 — Zero Stock Display Rules

Products are **never removed** from the Inventory page when On Hand reaches zero. Display rules:

| Condition | Badge colour | Sort position |
|---|---|---|
| On Hand > reorder_point | 🟢 In Stock (green) | Top |
| 0 < On Hand ≤ reorder_point | 🟡 Low Stock (amber) | Middle |
| On Hand = 0 | 🔴 Out of Stock (red) | Bottom |

A product remains visible with "Out of Stock" badge if:
- `warehouseId` exists in `product.stock`, OR
- Any pending transfer or adjustment references the product at this warehouse

---

### A4 — Issue and Receive Stock

- Warehouse field is **read-only**, auto-populated from the authenticated user's JWT `warehouseId` — no dropdown
- **Issue Stock**: single ISSUE ledger entry with negative quantity. No RESERVE transaction at any point.
- **Receive Stock**: single RECEIVE ledger entry with positive quantity. Immediate On Hand increase.
- Both require approval routing if quantity exceeds the tenant's configured approval thresholds.

---

### A5 — Adjustment Rules

| Reason code | Sign enforcement | Notes |
|---|---|---|
| DAMAGE | Always negative | Stock destroyed in warehouse |
| EXPIRY | Always negative | Expired product disposal |
| SUPPLIER_RETURN | Always negative | Return outbound |
| COUNT_VARIANCE | Signed (caller) | Physical count result |
| OTHER | Signed (caller) | Dual add/remove input |

- Zero floor enforced by `record_transaction()` — HTTP 422 if deduction would go below 0
- Override requires `dispatch:fefo_override` permission (or equivalent override flag) + audit log entry
- Approval thresholds per `APPROVAL_DEFAULTS` in `wizard_service.py`

---

## §B — Org Hierarchy & Personnel Design

### B1 — Hierarchy Model

The platform supports a flexible, configurable hierarchy of 1–5 levels per tenant. Design principles:

- Maximum 5 levels (Level 0–4 in `tenant_hierarchy_config`)
- Level names are tenant-configurable (e.g. "Region", "Warehouse", "Store")
- Multiple root nodes are supported (e.g. two separate factories under one tenant)
- Each node independently opts in or out of physical stock holding (`is_stock_holding`)
- Non-stock nodes participate in the approval chain only — they do not hold inventory
- All data stored in `tenant_hierarchy_config` + `organization_node` + `org_node_hierarchy`

---

### B2 — Level Configuration

Each tenant configures levels during the onboarding wizard. Per level:

| Field | Type | Description |
|---|---|---|
| `level_number` | INTEGER 1–5 | Position in hierarchy (1 = top) |
| `level_name` | VARCHAR(100) | Tenant-defined display name (e.g. "Region") |
| `default_role_code` | role_code | System role auto-suggested for this level |
| `role_display_label` | VARCHAR(100) | How tenants name that role (e.g. "Area Manager") |
| `is_stock_holding` | BOOLEAN | Whether nodes at this level hold physical inventory |
| `is_active` | BOOLEAN | Whether this level is in use |

**Example level mapping (5-level distributor):**

| Level | System Role | Display Label | Stock Holding |
|---|---|---|---|
| 1 | NM | General Manager | No (approval only) |
| 2 | RM | Regional Director | No (approval only) |
| 3 | RM | Area Manager | No (approval only) |
| 4 | WM | Distribution Centre Manager | Yes |
| 5 | WM | Store Manager | Yes |

The system role codes are fixed and immutable. Display labels are tenant-specific and stored separately from the role codes.

---

### B3 — Product Scoping

**Standard products** (`source_factory_id IS NULL`): visible everywhere in the tenant, pullable from any node with available stock.

**Factory-specific products** (`source_factory_id SET`):
- Visible to all nodes in the tenant (full stock transparency — operators can see stock exists)
- PULL source is locked to the home factory's subtree
- Backend validates source on every PULL creation: raises `INVALID_SOURCE_FACTORY` (HTTP 422) if source is outside the factory subtree
- Frontend filters source warehouse dropdown to show only nodes within the home factory subtree
- Badge displayed on product card: `Source: [Factory Name] only`

**New schema field required:**
```sql
ALTER TABLE products ADD COLUMN source_factory_id UUID REFERENCES organization_node(id);
```

---

### B4 — Supply Routes

**Auto-suggested defaults** (applied at org setup):
- Primary source = direct parent node in the reporting hierarchy
- Secondary source = grandparent node (fallback when primary is out of stock)

**Admin override**: any node in the tenant may be set as a supply source via the org setup UI. Override stored in `org_node_hierarchy` as a `SUPPLY_FROM` relationship.

Supply route changes are audit-logged with the before and after node IDs.

---

### B5 — Personnel Assignment Model

Three assignment types for a user's facility access:

| Type | Count per user | Duration | Who creates | Higher approval? |
|---|---|---|---|---|
| PRIMARY | Exactly 1 | Permanent | SA/TA (onboarding) | N/A |
| ACTING | Multiple | Time-bounded (valid_from, valid_until) | Any manager for users in their scope | Not required |
| DELEGATE | Multiple | Time-bounded, permission-scoped | Any manager for users in their scope | Not required |

**JWT rule**: `warehouse_id` in JWT always equals the user's PRIMARY facility.

**Permission evaluation**: ABAC checks union PRIMARY + all currently-active ACTING/DELEGATE assignments. Expired assignments are ignored.

**New table required:**
```sql
CREATE TABLE user_facility_assignments (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES tenants(id),
  user_id        UUID NOT NULL REFERENCES users(id),
  facility_id    UUID NOT NULL REFERENCES organization_node(id),
  assignment_type VARCHAR(20) NOT NULL,  -- 'PRIMARY' | 'ACTING' | 'DELEGATE'
  role_code      role_code NOT NULL,
  valid_from     TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until    TIMESTAMPTZ,            -- NULL = permanent
  created_by     UUID NOT NULL,
  notes          TEXT,
  is_active      BOOLEAN NOT NULL DEFAULT true,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Every assignment change is audit-logged with before/after state.

---

### B6 — Role System

System role codes are fixed and must never be renamed or removed:
`SA, TA, NM, RM, LM, WM, AU, RT, SA_GT, SYS`

**Tenant-configurable display labels**: stored in `tenant_hierarchy_config.role_display_labels` as JSONB:
```json
{"NM": "General Manager", "RM": "Regional Manager", "WM": "Store Manager"}
```

**Role-to-level mapping**: configured per tenant during org setup wizard. The system auto-suggests based on level position, but manual override is always permitted.

---

### B7 — Personnel Page Design

Access scoped by the manager's authority subtree (`get_authority_scope()`).

**List view** — columns: Name, Email, Role (display label), Facility, Status, Active Assignments

**Add user form** — fields:
- Full name, email address
- Role (dropdown limited to roles below the creating manager's own level)
- Primary facility (all active nodes in tenant shown, with hierarchy breadcrumb)
- Initial password (forced reset on first login)

**Acting assignment form** — fields:
- User (any user in manager's scope)
- Acting facility, acting role
- Valid from, valid until dates
- Notes (required)

**Actions:**
- Deactivate user → `is_active = false`, all active ACTING/DELEGATE assignments also closed
- Reactivate user → `is_active = true`, new assignments created as needed
- Hard delete is never permitted

All form submissions are audit-logged.

---

### B8 — Multiple NM Routing

Some tenants configure more than one National Manager (NM role, privilege level 8). This is valid because tenants may have parallel divisions (e.g., a factory NM and a distribution NM) that are both modelled as Level 1 or Level 2 nodes in the hierarchy.

**How approval routing works when multiple NMs exist:**

1. **Node-scoped approval**: Approval requests route to the NM whose `authority_scope` (from `get_authority_scope()`) includes the requesting warehouse node. If exactly one NM covers the requesting node, that NM receives the request.

2. **Ambiguous scope (multiple NMs cover the same node)**: When `get_authority_scope()` returns multiple candidates at NM privilege level, the system routes to **all matching NMs in parallel**. The first NM to act (approve or reject) resolves the request; subsequent actions by other NMs are ignored (idempotency key prevents double-processing).

3. **No NM covers the node**: Falls back to `TA` (Tenant Admin, privilege level 9) — the tenant's ultimate authority.

**Frontend display rule**: The transfer detail page shows all pending approver names when multiple NMs are in the routing path, separated by " or " (e.g., "Awaiting approval from Abebe Kebede or Tigist Haile").

**Backend implementation**: `get_approval_routing()` in `approval_service.py` returns a list of `(user_id, role)` tuples. Multiple entries at the same privilege level trigger parallel notification via the outbox (one `ApprovalRequired` event per approver). The approval is resolved when any one approver acts.

**Constraint**: This behaviour only applies when multiple NMs have overlapping authority scopes for the same requesting node. Multiple NMs at different parts of the hierarchy (non-overlapping scopes) each receive only the requests within their own scope.

---

## §C — Phase 4B Architecture Decisions

### C1 — Gateway vs BFF Mode

The frontend supports two modes simultaneously in the same codebase:

| Mode | Condition | Data source |
|---|---|---|
| BFF / Demo | `NEXT_PUBLIC_API_URL` unset | Next.js API routes + Zustand in-memory state |
| Gateway | `NEXT_PUBLIC_API_URL=http://localhost:8000` | Real FastAPI + PostgreSQL via HTTP proxy |

Switching between modes requires only an environment variable change — no code changes.

---

### C2 — Local Dev Auth Bypass

When `ENVIRONMENT=local`, the auth service accepts `POST /api/v1/auth/token` with `{ "dev_email": "..." }` and returns a real JWT using seed UUIDs from the database. This bypass exists only for local development and is gated by the `ENVIRONMENT` variable.

**This bypass must be removed before AWS deployment.** It must not appear in any stage or prod environment.

---

### C3 — Balance Calculation Architecture

Two mutually exclusive paths — never mix:

| Mode | Balance source | Zustand used? |
|---|---|---|
| Gateway | API fields only: `current_stock`, `pending_out_qty`, `in_transit_out_qty`, `in_transit_in_qty`, `net_available` | Read-only (transfer history) |
| BFF/Demo | Zustand store calculations (`getOnHand`, `getReserved`, etc.) | Yes |

`safeFloat()` helper is required for all API balance fields to guard against `null` / `undefined` → `NaN` propagation.

---

## §D — AWS Verification Checklist

Items confirmed working in local gateway mode. Must be re-verified after AWS deployment with real RDS, ElastiCache, and Cognito JWTs.

| # | Item | Local status | AWS status |
|---|---|---|---|
| 1 | Products page balance consistency across warehouses | ✅ Verified local | ⏳ Pending |
| 2 | Balance persistence across browser refresh | ✅ Verified local | ⏳ Pending |
| 3 | Adjustment balance update after RM/NM/TA approval | ✅ Verified local | ⏳ Pending |
| 4 | Transfer in-transit balance on both source and destination | ✅ Verified local | ⏳ Pending |
| 5 | RLS tenant isolation under real Cognito JWTs | ⏳ Not tested | ⏳ Pending |
| 6 | Outbox worker processing under Celery + ElastiCache | ⏳ Not tested | ⏳ Pending |
| 7 | Auth service Cognito integration (replace dev_email bypass) | ⏳ Not tested | ⏳ Pending |
| 8 | ECS Fargate container health checks and rolling deployments | ⏳ Not tested | ⏳ Pending |
| 9 | Secrets Manager injection at ECS task startup | ⏳ Not tested | ⏳ Pending |

---

## §E — Deferred Features

Features fully designed but not yet implemented, pending AWS environment or specific dependencies:

| Feature | Blocked by | Spec location |
|---|---|---|
| Offline mode (IndexedDB sync + service worker) | Testing complexity without real devices | CLAUDE.md §18 |
| Email/SMS alerts | AWS SES + SNS | CLAUDE.md §8 (outbox event handlers) |
| Cognito authentication (replace dev_email) | AWS Cognito provisioning | CLAUDE.md §6 |
| GitHub Actions CI/CD pipeline | AWS OIDC role provisioning | CLAUDE.md §22 |
| Oromifa `or.json` native-speaker review | Staffing decision | CLAUDE.md §12 |
| Amazon OpenSearch | Conditional — tenant request only | CLAUDE.md §2 |
| Barcode scanning (live device test) | Physical Android hardware | CLAUDE.md §11 |
| Flutter native app | Phase 3 decision point | CLAUDE.md §26 |

---

*PRD Appendix v1.0 — SMART Inventory Platform*  
*Created: 2026-05-26 · Maintained alongside CLAUDE.md*
