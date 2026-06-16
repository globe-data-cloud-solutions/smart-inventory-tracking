# SMART Inventory — PRD Amendment Log

**Document Version:** 1.0
**Date:** 2026-06-15
**Status:** Living document
**Base PRD:** SMART_Inventory_PRD_v4.docx
**Purpose:** Captures all design decisions, rule changes, and feature additions made during
implementation that are NOT reflected in PRD v4. Use this document as the source for the next
formal PRD version update.

---

## Amendment Entry Format

Each entry uses this structure:
- **AMD-ID** — unique identifier
- **Date** — when decision was made
- **PRD Section** — affected section or action number in PRD v4
- **Type** — CHANGE | ADDITION | REMOVAL | CLARIFICATION
- **Original PRD Rule** — what PRD v4 said (or "Not in PRD" if new)
- **New Rule** — what was implemented
- **Reason** — why the change was made
- **Commit** — git commit reference(s)
- **Status** — IMPLEMENTED | PLANNED | DEFERRED

---

## Section 1 — Permission Changes

### AMD-001 — Audit Log Access for NM/RM/WM/LM

- **Date:** 2026-06-15
- **PRD Section:** §14, Action #10 "Audit Tenant Activity"
- **Type:** CHANGE
- **Original PRD Rule:** NM/RM/WM/LM have NO access to audit log (Action #10 grants: SA=Y, TA=Y,
  NM/RM/WM/LM=N, AU=Y)
- **New Rule:**
  - TA/SA/AU/NM → tenant-wide audit log access (all actions)
  - WM/RM/LM → facility-subtree scoped access (own actions UNION actions on their facility's
    transfers/adjustments)
  - All roles can see acted_on_behalf_of entries relevant to their facility
- **Reason:** Operational managers need visibility into activity on their own facilities (especially
  when TA/NM acts on their behalf). Pure "None" access was too restrictive for day-to-day use.
  AU's existing full access made explicit (was accidental via warehouse_id=None fallthrough).
- **Commit:** e0b2abb, 3a7815a, e22b6ab, 6f6eee5
- **Status:** IMPLEMENTED

---

### AMD-002 — New Read-Only Permission Grants (Migrations 054-057)

- **Date:** 2026-06-15
- **PRD Section:** §14 Permission Matrix
- **Type:** ADDITION
- **Original PRD Rule:** Not in PRD
- **New Rule:** Added read-only grants for WM/RM/LM to support the Approval Policies reference page:
  - tenant:self_approval_view → WM, RM, LM
  - adjustment_approval_rule:view → WM, RM, LM
  - transfer_approval_rule:view → WM, RM, LM
  - position:view → WM, RM, LM, NM, SA, AU
  - transfer_type:view → all roles
  - product:list/product:view → LM
- **Reason:** Required for new Approval Policies reference page (AMD-009). Read-only — no write
  access changes.
- **Commit:** 9154c23
- **Status:** IMPLEMENTED

---

## Section 2 — Architecture Decisions

### AMD-003 — Approval Routing Uses position_id UUID FK

- **Date:** 2026-06-15
- **PRD Section:** §17 Transfer Approval Routing
- **Type:** CHANGE (GAP C fix)
- **Original PRD Rule:** Approval routing referenced approver by position title string
- **New Rule:** All approval routing uses position_id UUID FK (not position title string). Position
  renames do not break existing approval rules.
- **Reason:** Position title strings are mutable — renaming a position would silently break all
  approval rules referencing it. UUID FK survives renames.
- **Commit:** e8dc5e0, e2018fa
- **Status:** IMPLEMENTED

---

### AMD-004 — warehouse_stock is Computed Read Model

- **Date:** 2026-06-15
- **PRD Section:** §8 Inventory Architecture
- **Type:** CLARIFICATION
- **Original PRD Rule:** Not explicitly stated
- **New Rule:** warehouse_stock table is a computed read model — NEVER directly writable. Enforced
  via PostgreSQL RULE:
  ```sql
  CREATE RULE no_direct_stock_update AS ON UPDATE TO warehouse_stock
    WHERE current_setting('app.ledger_write_allowed', true) IS DISTINCT FROM 'true'
    DO INSTEAD NOTHING;
  ```
  All stock changes go through the immutable ledger only.
- **Reason:** Prevents accidental direct writes that would corrupt the audit trail and ledger
  integrity.
- **Commit:** See CLAUDE.md §14
- **Status:** IMPLEMENTED

---

### AMD-005 — DIRPUSH Dropped

- **Date:** 2026-06-15
- **PRD Section:** §17 Transfer Types
- **Type:** REMOVAL
- **Original PRD Rule:** DIRPUSH was a named transaction type
- **New Rule:** DIRPUSH is explicitly dropped. Active transfer types: PULL, PUSH, SISTER only.
  Direct push from a higher facility to a sub-facility bypassing intermediate levels is modelled
  as a standard PUSH transaction whose SUPPLY_FROM relationship in org_node_hierarchy spans
  non-adjacent hierarchy levels.
- **Reason:** Redundant with PUSH type; dual-confirm + audit trail via PUSH covers all DIRPUSH
  use cases.
- **Commit:** See CLAUDE.md §1 absolute constraints
- **Status:** IMPLEMENTED

---

### AMD-006 — Multi-Source Split Request Idempotency

- **Date:** 2026-06-15
- **PRD Section:** §17 Transfer Architecture
- **Type:** ADDITION
- **Original PRD Rule:** Not in PRD
- **New Rule:** Multi-source split requests use parent_transfer_id to link legs. Each leg is an
  independent transaction with its own idempotency key. parent_transfer_id enables atomic rollback
  and reporting across legs. Parent record status is read-only — derived from the aggregate state
  of all legs and never set directly by application code.
- **Reason:** Required for transfers drawing from multiple source warehouses simultaneously.
- **Commit:** See CLAUDE.md §7 (inventory_transactions schema), Business Rule #24
- **Status:** IMPLEMENTED

---

## Section 3 — Feature Additions

### AMD-007 — Self-Approval Feature

- **Date:** 2026-06-15
- **PRD Section:** §17 Approval Routing
- **Type:** ADDITION
- **Original PRD Rule:** Not in PRD
- **New Rule:** Tenants can configure self-approval policies per role/level/transaction type with
  qty_limit and value_limit. Below the limit: auto-approved. Above: routes to configured approver.
  Covers transfers (PULL/PUSH/SISTER) and adjustments. Cost price display included for TA approval
  decisions.
  - Tables: self_approval_policies, adjustment_approval_rules
  - UI: Tab 3 (self-approval limits), Tab 5 (adjustment approval rules) in Tenant Settings
  - Engine: check policy at submission, skip approval if within limit, set is_self_approved=true
- **Commit:** 5dc2210 (P2 schema), b0b6f36 (P3 UI), 75fb07e (P4 adj rules UI), 8c85d0f (P5
  transfer engine), ab9103a (P6 adjustment engine), d4d73ed (P5 fixes)
- **Status:** IMPLEMENTED

---

### AMD-008 — "Acting on Behalf Of" Indicator

- **Date:** 2026-06-15
- **PRD Section:** §17 Transfer Lifecycle / §16 Audit Log
- **Type:** ADDITION
- **Original PRD Rule:** Not in PRD
- **New Rule:** When TA/NM/SA (warehouse_id=None roles) issue or dispatch a transfer whose source
  warehouse belongs to a lower-level facility:
  - Frontend: badge shown near Issue/Dispatch buttons
  - Backend: acted_on_behalf_of field added to audit_log abac_context JSONB
  - Visible to affected facility managers in their audit log (facility-subtree scoping)
- **Commit:** 9290311 (feature), bc52540 (SQL fix), 25e32bc (guard fix), 0dedc09 (frontend render)
- **Status:** IMPLEMENTED

---

### AMD-009 — Approval Policies Reference Page

- **Date:** 2026-06-15
- **PRD Section:** Not in PRD
- **Type:** ADDITION
- **Original PRD Rule:** Not in PRD
- **New Rule:** New read-only page /app/[org]/approval-policies, accessible to all roles. Shows:
  - Section 1 (non-TA): plain-language own approval limits with concrete examples
  - Section 2 (all roles): controlled products list with plain-language override rules
  - Section 3 (TA/SA only): full policy matrix — configured approval rules (from
    transfer_approval_rules) AND self-approval limits, per transaction type, using tenant's
    custom labels throughout
  - Live data, reflects edits immediately on reload
- **Commit:** 9154c23 (page), a20ddb8 (TA direct view fix), fc13a8c (Section 3 transfer rules)
- **Status:** IMPLEMENTED

---

### AMD-010 — Custom Transfer Type Display Names

- **Date:** 2026-06-15
- **PRD Section:** §17 Transfer Types
- **Type:** ADDITION
- **Original PRD Rule:** Transfer types shown as PULL/PUSH/SISTER (system codes)
- **New Rule:** transfer_type_config table stores per-tenant display_name and description for each
  transfer type. Display names used throughout UI:
  - Transfer page dropdown
  - Approval Policies page
  - Minimum Approval Level section in Add/Edit Product panel
  - Fallback to i18n defaults if not configured
- **Commit:** ab492a5
- **Status:** IMPLEMENTED

---

### AMD-011 — Audit Log Frontend Architecture

- **Date:** 2026-06-15
- **PRD Section:** §16 Audit Log
- **Type:** CHANGE
- **Original PRD Rule:** Not specified (was localStorage-only Zustand store — demo artifact)
- **New Rule:**
  - Audit log page reads from backend audit_logs table via GET /api/v1/audit-log/
  - Role-based scoping enforced at backend (per AMD-001)
  - Entries enriched with from_warehouse_name, to_warehouse_name, product_summary, user_name via JOINs
  - acted_on_behalf_of displayed per AMD-008
  - Default view hides SYSTEM category + *:view/*:list actions (toggle: "Show system activity")
  - Pagination supported
  - localStorage store (useAuditStore) retained for writes but no longer the source of truth for display
- **Commit:** e0b2abb (wire backend), 3a7815a (enrichment), e22b6ab (SQLAlchemy colon fix),
  6f6eee5 (category filter), b67fa76 (resource_type consistency)
- **Status:** IMPLEMENTED

---

### AMD-012 — SISTER Transfer Excluded from Product Overrides

- **Date:** 2026-06-15
- **PRD Section:** §17 Controlled Products / Approval Overrides
- **Type:** CLARIFICATION
- **Original PRD Rule:** Not explicitly stated
- **New Rule:** SISTER (Branch Exchange) transfers are explicitly excluded from product-level
  approval overrides. SISTER uses dual-confirm + audit trail as industry-standard lateral transfer
  control — not escalation-based approval.
- **Reason:** Web research confirmed: peer-level dual approval is the standard pattern for lateral
  transfers, not escalation.
- **Commit:** See product override design decisions (44b4021, f5e1fa1)
- **Status:** IMPLEMENTED

---

## Section 4 — UI/UX Decisions

### AMD-013 — Issue Stock Hidden

- **Date:** 2026-06-15
- **PRD Section:** §11 Inventory Management UI
- **Type:** REMOVAL
- **Original PRD Rule:** Issue Stock shown as distinct UI action
- **New Rule:** Issue Stock hidden from UI. Adjustment covers all stock correction use cases.
  Issue as a distinct action removed to simplify the operational workflow.
- **Commit:** 93cc585
- **Status:** IMPLEMENTED

---

### AMD-014 — Advise Button Removed

- **Date:** 2026-06-15
- **PRD Section:** §17 Transfer Lifecycle
- **Type:** CHANGE
- **Original PRD Rule:** ADVISED status and Advise button shown in transfer UI
- **New Rule:** Advise button removed from transfer UI. ADVISED status retained in backend state
  machine (not removed — may be used by future integrations or API consumers). UI simplified to
  core lifecycle actions only.
- **Commit:** 93cc585
- **Status:** IMPLEMENTED

---

### AMD-015 — Discontinued Products Zero-Balance Validation

- **Date:** 2026-06-15
- **PRD Section:** §10 Product Management
- **Type:** ADDITION
- **Original PRD Rule:** Products can be discontinued (no explicit balance check stated)
- **New Rule:** Products cannot be discontinued if any warehouse holds a non-zero balance.
  Validation runs at API layer before status change. Error response lists the warehouse
  locations holding remaining stock.
- **Reason:** Prevents orphaned inventory from appearing in stock counts after discontinuation.
- **Commit:** 495d3c8, c473e5d
- **Status:** IMPLEMENTED

---

### AMD-016 — Inventory Page Display Scoped by Level

- **Date:** 2026-06-15
- **PRD Section:** §11 Inventory Management
- **Type:** CLARIFICATION
- **Original PRD Rule:** Not explicitly stated
- **New Rule:**
  - L1 (NM/TA): sees all products across tenant
  - L2+ (RM/WM): sees only products that have stock at their facility or below
- **Reason:** Reduces noise for warehouse-level users — showing thousands of products with zero
  stock at their facility is not useful operationally.
- **Commit:** c473e5d
- **Status:** IMPLEMENTED

---

## Section 5 — Planned (Not Yet Built)

### AMD-017 — Tiered Commercialization

- **Date:** 2026-06-15
- **PRD Section:** Not in PRD
- **Type:** ADDITION (PLANNED)
- **Original PRD Rule:** Not in PRD (plan_feature ABAC attribute referenced but not implemented)
- **New Rule (planned):**
  - plan_tier ENUM (STARTER/PROFESSIONAL/ENTERPRISE) on tenants table
  - feature_flags JSONB on tenants table for per-feature gating
  - Plan-check middleware runs BEFORE permission checks
  - Tier presets define feature_flag bundles
  - Limits enforcement: max_products, max_warehouses, max_users
  - Phase 1 (before launch): schema + middleware + frontend flag-aware UI
  - Phase 2 (after first customers): limits enforcement + Stripe billing + usage analytics
- **Commit:** Not yet implemented
- **Status:** PLANNED

---

### AMD-018 — GAP B: Stuck Transfers When Approver Deactivated

- **Date:** 2026-06-15
- **PRD Section:** §17 Approval Routing
- **Type:** ADDITION (DEFERRED)
- **Original PRD Rule:** Not in PRD
- **New Rule (planned):**
  When a transfer is PENDING_APPROVAL and the assigned approver's position becomes vacant (user
  deactivated or reassigned):
  - Detection: periodic Celery task checks for stuck transfers
  - Resolution options (TA decides):
    a. Auto-escalate to next level
    b. Alert TA to manually reassign
    c. TA re-routes approval step to different position
- **Commit:** Not yet implemented
- **Status:** DEFERRED (Phase 2)

---

### AMD-019 — Product Images + Tenant Branding

- **Date:** 2026-06-15
- **PRD Section:** Not in PRD
- **Type:** ADDITION (PLANNED)
- **Original PRD Rule:** Not in PRD
- **New Rule (planned):**
  - products.image_url (nullable)
  - tenants.logo_url (nullable)
  - tenants.banner_url (nullable)
  - StorageService abstraction (LocalStorageService now, S3StorageService via config later)
  - Upload endpoints
  - Product image in product cards
  - Tenant logo in top nav/header
  - Tenant banner in dashboard
- **Commit:** Not yet implemented
- **Status:** PLANNED

---

### AMD-020 — Section 3 Transfer Rules Matrix (Approval Policies)

- **Date:** 2026-06-15
- **PRD Section:** Not in PRD
- **Type:** ADDITION
- **Original PRD Rule:** Not in PRD
- **New Rule:** Approval Policies page Section 3 (TA/SA view) shows configured transfer_approval_rules
  directly (priority, source/dest level, ranges, approval steps with resolved position labels)
  alongside self-approval limits — two clearly-separated subsections per transaction type.
  Adjustment shown in Self-Approval Limits only (no separate Configured Rules subsection).
  "Any level" footnote shown when applicable.
- **Commit:** fc13a8c
- **Status:** IMPLEMENTED

---

## Section 6 — Bug Fixes with Design Impact

### AMD-021 — Dynamic Tenant Position Hierarchy (GAP A + C)

- **Date:** 2026-06-15
- **PRD Section:** §17 Transfer Approval, §14 RBAC
- **Type:** CHANGE (GAP A + C resolution)
- **Original PRD Rule:** Approval steps tracked by role code; reviewer determined by hardcoded
  role hierarchy
- **New Rule:**
  - Multi-step sequential approval enforced via current_approval_step integer on transfer_orders
  - Approval steps advance only when the currently-assigned position holder acts
  - position_id stored in resolved_approval_steps JSONB (not title string) — cascade title update
    on rename
  - Reviewer for PENDING_REVIEW uses tenant hierarchy levels (not hardcoded 3-level assumption)
    — fixes stuck PENDING_REVIEW in 3-level orgs
  - Positions dropdown for approval override uses live tenant positions, not hardcoded role codes
- **Commit:** f231fa8 (GAP A), e8dc5e0 (GAP C), e2018fa (bindparam + model_dump fix),
  26dda0d (hierarchy level fix), c6ec310 (dynamic positions everywhere)
- **Status:** IMPLEMENTED

---

### AMD-022 — Adjustment Quantity Field Rename

- **Date:** 2026-06-15
- **PRD Section:** §17 Adjustments
- **Type:** CHANGE
- **Original PRD Rule:** Field named quantity in adjustment API
- **New Rule:** Field renamed to quantity_delta throughout — POST body, AdjRecord TypeScript type,
  and all usages. Signed value: negative = stock reduction, positive = stock addition.
- **Reason:** quantity was ambiguous — delta makes the signed nature explicit and prevents callers
  from sending an absolute value where a signed delta is required.
- **Commit:** 6026ffe, d5bc9b6
- **Status:** IMPLEMENTED

---

### AMD-023 — Decimal Formatting Standardized Across UI

- **Date:** 2026-06-15
- **PRD Section:** Not specified in PRD v4
- **Type:** CLARIFICATION/ADDITION
- **Original PRD Rule:** Not explicitly stated — DECIMAL(15,4) DB storage was specified but display
  format was not
- **New Rule:** All quantity and value fields display with maximum 2 decimal places, trailing zeros
  stripped (e.g. "27000" not "27000.0000", "25.57" not "25.5700"). Applies to:
  - Approval Policies page (qty_limit, value_limit, thresholds)
  - Inventory page tables (on_hand, in_transit, available)
  - Transfer/adjustment panels and lists (quantity columns)
  - Dashboard stock totals and reorder points
  - Lots page quantities

  Implemented via shared `formatQty()` utility in `frontend/src/lib/utils.ts` using
  `toLocaleString('en-US', {maximumFractionDigits: 2})`. Underlying DB storage remains
  DECIMAL(15,4) — display only.
- **Commit:** 3bf8bc3
- **Status:** IMPLEMENTED

---

## Section 7 — Test Infrastructure

### AMD-024 — Tenant 07 End-to-End Test Suite

- **Date:** 2026-06-15
- **PRD Section:** Not in PRD (new artifact)
- **Type:** ADDITION
- **Original PRD Rule:** Not in PRD
- **New Rule:** Created living test infrastructure for full end-to-end regression testing:

  **scripts/setup_tenant07.py** — idempotent setup script creating:
  - Tenant "Test Organization Seven" (tenant-07, ID: 07000007-...)
  - 4-level hierarchy with 2 L1 factories (Factory A: 4-level; Factory B: mixed 3/4-level depth)
  - 14 org nodes, 30 positions, 31 users (2 per node, main + assistant), AU + LM tenant-wide
  - 5 products (3 standard, 2 controlled with ALWAYS/QUANTITY overrides)
  - Realistic approval rules (9 transfer + 4 adjustment rules)
  - Opening stock across all 7 warehouses

  **tests/e2e/test_tenant07_e2e.py** — 118 tests across 11 groups:
  Setup Verification, Authentication, Products, PULL/PUSH/SISTER Transfers, Adjustments,
  Permissions, Audit Log, Org & Stock.
  Runs against live local backend (not mocked). Idempotent — safe to re-run. All test data
  left intact after run (no cleanup).

  Current status: 115 PASS / 0 FAIL / 3 SKIP (T04 cross-tenant tests pending T04 credential fix).

  Planned additions: Groups 12–19 covering controlled product routing, data integrity,
  multi-tenant isolation, approval edge cases, performance, i18n, security.
- **Commit:** 88c4689 (suite + setup script), 48bdc50 (stock depletion fixes — UUID-keyed prereqs)
- **Status:** IMPLEMENTED (ongoing)

---

## Appendix — Key Commits Reference

| Commit | Description |
|--------|-------------|
| 30a2663 | fix: NameError is_controlled in update_product() |
| 4c19a9d | fix: approval-minimums validation + test coverage |
| 9290311 | feat: acting_on_behalf_of badge + custom transfer type names |
| bc52540 | fix: _get_warehouse_name SQL bug (SQLAlchemy colon) |
| 25e32bc | fix: acted_on_behalf_of guard excluded NM/TA/SA incorrectly |
| 0dedc09 | feat: display acted_on_behalf_of in audit log frontend |
| e0b2abb | fix: wire audit log to backend (replaces localStorage display) |
| 3a7815a | feat: audit log enrichment + system activity toggle |
| e22b6ab | fix: SQLAlchemy literal colon bug in include_views=false |
| 6f6eee5 | fix: audit log category filter (TRANSFER/INVENTORY vs SYSTEM) |
| b67fa76 | fix: transfer:step_approved resource_type consistency |
| ab492a5 | feat: custom transfer type names in Minimum Approval Level |
| 9154c23 | feat: Approval Policies reference page |
| a20ddb8 | fix: TA/SA see full matrix directly (no generic fallback) |
| fc13a8c | feat: Section 3 shows configured transfer approval rules |
| 3bf8bc3 | fix: decimal formatting ≤ 2 places everywhere |
| f231fa8 | fix: multi-step sequential approval (GAP A) |
| e8dc5e0 | fix: position_id in approval steps (GAP C) |
| 26dda0d | fix: hierarchy levels for reviewer (3-level org fix) |
| c6ec310 | feat: dynamic tenant positions everywhere |
| 5dc2210 | feat: self_approval_policies + adjustment_approval_rules tables |
| 8c85d0f | feat: transfer self-approval engine |
| ab9103a | feat: adjustment self-approval engine |
| 6026ffe | fix: quantity → quantity_delta in adjustment POST body |
| 93cc585 | fix: hide Issue Stock button; remove Advise button |
| c473e5d | feat: level-based inventory display; discontinued validation |
| 3bf8bc3 | fix: decimal formatting ≤ 2 places everywhere (AMD-023) |
| 88c4689 | test: Tenant 07 e2e suite — 118 tests, 11 groups, setup script |
| 48bdc50 | test: e2e stock depletion fixes — UUID-keyed prereqs |

---

*Last updated: 2026-06-16*
*Next PRD version: v5.0*
*Maintained by: Development team*
*Review before: First customer onboarding*
