# APPROVAL WORKFLOW REPORT
> SMART Inventory Platform — Diagnostic only, no code changes  
> Generated: 2026-05-30  
> Sources: `approval_service.py`, `inventory_service.py`, `state_machine.py`, `transfer.py`, `CLAUDE.md §17 §24`, `PRD-APPENDIX.md §A1 §A2 §B9 §D2`

---

## SECTION 1 — Core Rules Summary

Confirmed business rules (as implemented in `approval_service.py` and `inventory_service.py`):

1. **You cannot approve your own request.**  
   `transition_transfer()` compares `created_by` against `user.user_id`; raises HTTP 403 `CANNOT_APPROVE_OWN_TRANSFER` before authority check. The approval-info endpoint also sets `can_approve=false` when `is_own_transfer=true`.

2. **If requester = required approver → escalate up by one level.**  
   Condition: `required_level >= requester_authority_level` (remember: lower = higher authority, so this catches equal-level AND lower-authority cases). Formula: `required_level = max(1, requester_authority_level - 1)`. Auto-approve is suppressed when escalation fires.

3. **Product minimum overrides quantity threshold (take the more restrictive).**  
   `required_level = min(product_min, threshold_level)`. Lower number = higher authority = more restrictive. A product_min of NM (1) always wins over WM (4).

4. **Higher authority always wins (lower level number).**  
   Directly expressed by the `min()` in Step 3 of `resolve_approval()`.

5. **SISTER shares PULL tiers.**  
   `lookup_type = "PULL" if transaction_type == "SISTER" else transaction_type`. Applies in both Simple and Custom modes.

6. **Auto-approve notifies level above.**  
   When `decision.is_auto_approved`, `transition_transfer()` writes `AutoApprovalNotice` outbox events for each `notify_level` in `decision.notify_levels`. The notify list (e.g., `[2]` for "notify RM when WM auto-approves") is stored on the `approval_rule` row.

7. **Reserved shows at PENDING_APPROVAL, not DRAFT (per PRD-APPENDIX §A1).**  
   ⚠️ See Section 8 Gap #1 — RESERVE ledger entries are not written in the current code. The PRD-APPENDIX table describes intended behaviour; the current `transition_transfer()` does not write a RESERVE entry at PENDING_REVIEW or PENDING_APPROVAL. `warehouse_stock.reserved` is therefore always 0 in the current implementation.

---

## SECTION 2 — Authority Level Scale

Two parallel scales exist in `approval_service.py`. The **new authority scale** governs all `resolve_approval()` calls. The **old ROLE_LEVEL scale** is retained only for the legacy `ApprovalService.route_approval()`.

### New authority scale (lower = higher authority) — `ROLE_AUTHORITY_LEVEL`

| Role | System Code | Authority Level | Approval Capability | Notes |
|------|-------------|-----------------|---------------------|-------|
| System Admin | `SA` | 1 | All tiers (1–4) | Platform-level |
| Tenant Admin | `TA` | 1 | All tiers (1–4) | Highest tenant-scoped authority; CEO-equivalent |
| National Manager | `NM` | 1 | All tiers (1–4) | IMTS label: "General Manager" |
| Regional Manager | `RM` | 2 | Tiers 2, 3, 4 | IMTS: "Regional Manager" |
| Logistics Manager | `LM` | 3 | Tiers 3, 4 | Same privilege level as WM in old scale |
| Warehouse Manager | `WM` | 4 | Tier 4 only | Lowest approval authority with approval rights |
| Sales Agent | `SA_GT` | 5 | None | No approval authority |
| Retailer | `RT` | 5 | None | No approval authority |
| Auditor | `AU` | 5 | None | Read-only |
| System SYS | `SYS` | 5 | None | Internal automation only |

**Can-approve rule:** `caller_authority_level <= required_authority_level`  
Example: RM (level 2) CAN approve a tier requiring level 2, 3, or 4. RM CANNOT approve a tier requiring level 1 (NM/TA).

### Old ROLE_LEVEL scale (SA=10 highest) — legacy `ApprovalService` only

| Role | Old Level | Notes |
|------|-----------|-------|
| SA | 10 | Highest |
| TA | 9 | |
| NM | 8 | |
| RM | 7 | |
| WM | 6 | Same as LM |
| LM | 6 | Same as WM |
| SA_GT | 4 | |
| RT | 3 | |
| AU | 2 | |
| SYS | 1 | Lowest |

---

## SECTION 3 — Simple Mode Logic Trace

Simple mode: all transaction types share the same approval tiers (same rows for PULL, PUSH, SISTER, ADJUSTMENT stored in `approval_rule`).  

**Example tiers used throughout Section 3** (from the prompt — representative of typical seed data):

| Tier | Min Qty | Max Qty | Required Role | Authority Level | Auto-Approve |
|------|---------|---------|---------------|-----------------|--------------|
| Tier 1 | 0 | 99 | WM | 4 | Yes |
| Tier 2 | 100 | 999 | RM | 2 | No |
| Tier 3 | 1000+ | — | NM | 1 | No |

**Note on auto-approve:** Auto-approve fires only when ALL of these are true:
- `threshold.auto_approve = True`
- `product_min is None` (no product-level override)
- `required_level == threshold_level` (no product min narrowed it)
- No escalation fired

---

### WM creates PULL (requester_authority_level = 4)

| Qty | Tier | Threshold Role | Threshold Level | Escalate? | Formula | Final Level | Final Role | Auto? |
|-----|------|---------------|-----------------|-----------|---------|-------------|------------|-------|
| 50 | Tier 1 | WM | 4 | **YES** — 4 ≥ 4 | max(1, 4−1) = 3 | 3 | LM | No |
| 500 | Tier 2 | RM | 2 | No — 2 < 4 | — | 2 | RM | No |
| 2000 | Tier 3 | NM | 1 | No — 1 < 4 | — | 1 | NM | No |

**WM Tier 1 detail:** The WM auto-approve band fires escalation because the requester (WM, level 4) is at the same authority level as the required approver. `required_level (4) >= requester_level (4)` is true. Escalation bumps to LM (level 3). Auto-approve is suppressed regardless of the `auto_approve=True` flag on the band.

---

### RM creates PULL (requester_authority_level = 2)

| Qty | Tier | Threshold Role | Threshold Level | Escalate? | Formula | Final Level | Final Role | Auto? |
|-----|------|---------------|-----------------|-----------|---------|-------------|------------|-------|
| 50 | Tier 1 | WM | 4 | **YES** — 4 ≥ 2 | max(1, 2−1) = 1 | 1 | NM/TA | No |
| 500 | Tier 2 | RM | 2 | **YES** — 2 ≥ 2 | max(1, 2−1) = 1 | 1 | NM/TA | No |
| 2000 | Tier 3 | NM | 1 | No — 1 < 2 | — | 1 | NM | No |

**RM Tier 1 detail:** Tier 1 says WM (level 4) should approve, but RM (level 2) is requesting — RM has higher authority than WM, so WM cannot approve RM's own request. Escalation fires to level 1 (NM).

**RM Tier 2 detail:** Tier 2 says RM (level 2) should approve. RM is the requester. Same-level = escalate. Required becomes NM (level 1).

---

### NM creates PULL (requester_authority_level = 1)

| Qty | Tier | Threshold Level | Escalate? | Formula | Final Level | Final Role | Auto? | Notes |
|-----|------|-----------------|-----------|---------|-------------|------------|-------|-------|
| 50 | Tier 1 | 4 (WM) | **YES** — 4 ≥ 1 | max(1, 1−1) = max(1, 0) = 1 | 1 | NM/TA | No | Stays at 1; another NM/TA must approve |
| 500 | Tier 2 | 2 (RM) | **YES** — 2 ≥ 1 | max(1, 1−1) = 1 | 1 | NM/TA | No | Same — escalates to level 1 |
| 2000 | Tier 3 | 1 (NM) | **YES** — 1 ≥ 1 | max(1, 1−1) = 1 | 1 | NM/TA | No | Same |

**NM escalation ceiling detail:** All NM quantities escalate to level 1 (clamped by `max(1, ...)`). The result stays at level 1 — meaning another level-1 user (a different NM, TA, or SA) must approve. The "cannot approve own transfer" guard in `transition_transfer()` handles this: any NM who is NOT the creator may approve. See PRD-APPENDIX §B8 for parallel NM routing.

---

### TA creates PULL (requester_authority_level = 1)

Identical to NM — both are level 1:

| Qty | Final Level | Final Role | Auto? | Notes |
|-----|-------------|------------|-------|-------|
| 50 | 1 | NM/TA | No | Another TA or NM (not the creator) must approve |
| 500 | 1 | NM/TA | No | Same |
| 2000 | 1 | NM/TA | No | Same |

---

### PUSH transfers (simple mode — same tiers as PULL)

In simple mode, PUSH rules are stored in `approval_rule` under `transaction_type='PUSH'` with the same tier values as PULL. The escalation logic is identical.

| Requester | Qty | Tier | Escalate? | Final Role | Auto? |
|-----------|-----|------|-----------|------------|-------|
| WM (L4) | 50 | Tier 1 (WM L4) | YES → L3 | LM | No |
| WM (L4) | 500 | Tier 2 (RM L2) | No | RM | No |
| WM (L4) | 2000 | Tier 3 (NM L1) | No | NM | No |
| RM (L2) | 50 | Tier 1 (WM L4) | YES → L1 | NM | No |
| RM (L2) | 500 | Tier 2 (RM L2) | YES (same level) → L1 | NM | No |
| RM (L2) | 2000 | Tier 3 (NM L1) | No | NM | No |
| NM (L1) | Any | Any tier | YES (all escalate to L1) | Another NM/TA | No |

**PUSH state machine note:** PUSH has no `PENDING_REVIEW` step. DRAFT transitions directly to `PENDING_APPROVAL`. The ADVISED state (unique to PUSH) comes after APPROVED and before ISSUED — it is a notification step, not an approval step.

---

### SISTER transfers (shares PULL tiers)

SISTER always queries PULL approval rules: `lookup_type = "PULL"`. Escalation logic is identical.

| Requester | Qty | PULL Tier Hit | Escalate? | Final Role | Auto? |
|-----------|-----|--------------|-----------|------------|-------|
| WM (L4) | 50 | Tier 1 (WM L4) | YES → L3 | LM | No |
| WM (L4) | 500 | Tier 2 (RM L2) | No | RM | No |
| RM (L2) | 500 | Tier 2 (RM L2) | YES → L1 | NM | No |
| NM (L1) | Any | Any | YES → L1 | Another NM/TA | No |

**SISTER state machine note:** SISTER has two confirm steps before approval: `DRAFT → PENDING_SOURCE_CONFIRM → PENDING_DEST_CONFIRM → PENDING_APPROVAL`. Both WMs must explicitly confirm before approval routing begins. The approval-info endpoint would therefore only be meaningful once the transfer reaches `PENDING_APPROVAL`.

---

### ADJUSTMENT (simple mode — example tiers apply; org defaults differ)

Org-type defaults (used when no approval_rule rows exist):  
`0–99.9999 → WM`, `100–999.9999 → RM`, `1000+ → TA`

Using example tiers for trace consistency:

| Requester | Qty | Tier | Escalate? | Final Role | Auto? |
|-----------|-----|------|-----------|------------|-------|
| WM (L4) | 50 | Tier 1 (WM L4) | YES → L3 | LM | No |
| WM (L4) | 500 | Tier 2 (RM L2) | No | RM | No |
| RM (L2) | 50 | Tier 1 (WM L4) | YES → L1 | NM/TA | No |
| RM (L2) | 100 | Tier 2 (RM L2) | YES (same) → L1 | NM/TA | No |
| NM (L1) | Any | Any | YES → L1 | Another NM/TA | No |

**ADJUSTMENT state machine:** Terminal state is `POSTED`, not `RECEIVED`. No in-transit states. Machine: `DRAFT → PENDING_APPROVAL → APPROVED → POSTED`.

---

### RECEIVE / ISSUE (org defaults)

Org-type defaults: `0–199.9999 → WM (L4)`, `200+ → RM (L2)`.  
No auto-approve in org defaults (`auto_approve=False` on `_get_default_threshold()`).

| Requester | Qty | Default Role | Escalate? | Final Role | Auto? |
|-----------|-----|-------------|-----------|------------|-------|
| WM (L4) | 100 | WM (L4) | YES → L3 | LM | No |
| WM (L4) | 300 | RM (L2) | No | RM | No |
| RM (L2) | 100 | WM (L4) | YES → L1 | NM/TA | No |
| RM (L2) | 300 | RM (L2) | YES (same) → L1 | NM/TA | No |
| NM (L1) | Any | Any | YES → L1 | Another NM/TA | No |

**RECEIVE/ISSUE note:** These are direct stock operations (not transfer-order based). The approval path is conceptually the same but the approval workflow is routed through the adjustment or separate approval mechanism — not through `transition_transfer()`. The `_ORG_TYPE_DEFAULTS` for RECEIVE and ISSUE are defined in `approval_service.py` but no dedicated state machine exists for RECEIVE/ISSUE in `state_machine.py`.

---

## SECTION 4 — Custom Mode Logic Trace

In Custom mode, each transaction type stores its own tier rows in `approval_rule` with distinct `transaction_type` values.

### Fallback chain (from `resolve_approval()` code)

```
resolve_approval(simple_mode=False, transaction_type="PUSH")
  │
  ├─ Step 2a: _query_threshold(tenant_id, "PUSH", qty)
  │     → approval_rule WHERE tenant_id=:tid AND transaction_type='PUSH' AND product_id IS NULL
  │     → Found a row? → Use it.
  │
  ├─ Step 2b (custom mode fallback, only if Step 2a returned None):
  │     → _query_threshold(tenant_id, "PULL", qty)
  │     → Found a row? → Use it.
  │
  └─ Step 2c (always last resort):
        → _get_default_threshold("PUSH", qty)
        → Hardcoded _ORG_TYPE_DEFAULTS["PUSH"]
```

**SISTER is always PULL — regardless of mode:**
```python
lookup_type = "PULL" if transaction_type == "SISTER" else transaction_type
```
SISTER is remapped to PULL before any DB query. In custom mode, the SISTER-specific rows that `tiersToRules()` saves via `buildRules()` use `transaction_type='SISTER'` in the DB. However, `_query_threshold()` queries with `lookup_type='PULL'`. This means:
- In custom mode, if PULL tiers and SISTER tiers diverge in the UI, the SISTER DB rows are **never queried by `resolve_approval()`** — only PULL rows are used.
- This is by design (§D2.4) but is worth noting: the `approval_rule` rows saved for SISTER are effectively read by `ApprovalService.get_required_approver()` (legacy only), not by the new `resolve_approval()`.

### What changes in Custom mode vs Simple mode

| Aspect | Simple Mode | Custom Mode |
|--------|-------------|-------------|
| Tier storage | Same rows for all types (typically seeded once) | Separate rows per type |
| PUSH tiers | Same as PULL | Independent (e.g., higher thresholds for proactive pushes) |
| PULL tiers | Tenant-wide baseline | Configurable per scenario |
| SISTER | Uses PULL rows | Still uses PULL rows (always) |
| ADJUSTMENT | Same as PULL | Independent |
| Fallback path | `approval_rule.PULL → org defaults` | `approval_rule.TYPE → approval_rule.PULL → org defaults` |
| Auto-approve | Per tier flag | Per tier flag (same mechanism) |

---

## SECTION 5 — Product Minimum Override

Per-product minimum authority level stored in `product_approval_minimums.min_authority_level`. Queried in Step 1 of `resolve_approval()`.

**Key rule:** `required_level = min(product_min, threshold_level)`. Lower number is more restrictive. Product min always disables auto-approve when active.

---

### Example 1: WM creates PULL qty=50 — product minimum = NM (level 1)

```
Step 1: product_min = 1 (NM)
Step 2: Tier 1 → WM, threshold_level = 4, auto_approve = True
Step 3: required_level = min(1, 4) = 1
        is_auto = threshold.auto_approve(True) AND product_min IS None(False) → FALSE
Step 4: required_level(1) >= requester_level(4) → FALSE → no escalation
Result: NM approves. Auto-approve suppressed by product minimum.
Without product min: LM would approve (escalated from auto-approve WM tier).
```

---

### Example 2: RM creates PULL qty=50 — product minimum = LM (level 3)

```
Step 1: product_min = 3 (LM)
Step 2: Tier 1 → WM, threshold_level = 4, auto_approve = True
Step 3: required_level = min(3, 4) = 3
        is_auto = False (product_min is not None)
Step 4: required_level(3) >= requester_level(2) → TRUE → escalate
        required_level = max(1, 2−1) = max(1, 1) = 1 → NM
Result: NM approves. Product min set LM floor; escalation from RM requester pushed to NM.
```

---

### Example 3: WM creates PULL qty=200 — product minimum = WM (level 4)

```
Step 1: product_min = 4 (WM)
Step 2: Tier 2 → RM, threshold_level = 2, auto_approve = False
Step 3: required_level = min(4, 2) = 2 (RM wins — level 2 is more restrictive than level 4)
        is_auto = False (threshold.auto_approve=False; also product_min is not None)
Step 4: required_level(2) >= requester_level(4) → FALSE → no escalation
Result: RM approves. Product minimum of WM (L4) is less restrictive than the RM tier (L2);
        the tier wins. Product min only overrides when it is MORE restrictive (lower number).
```

---

### Example 4: WM creates ADJUSTMENT qty=50 — product minimum = TA (level 1)

```
Step 1: product_min = 1 (TA)
Step 2: Tier 1 → WM, threshold_level = 4, auto_approve = True
Step 3: required_level = min(1, 4) = 1
        is_auto = False (product_min is not None)
Step 4: required_level(1) >= requester_level(4) → FALSE → no escalation
Result: TA approves. Any qty adjustment on this product requires TA sign-off.
        Auto-approve on small quantities is always suppressed for this product.
```

---

## SECTION 6 — Status Transition and Balance Impact

Source: `PRD-APPENDIX.md §A1`, `inventory_service.py` (`transition_transfer`, `dispatch_transfer`, `receive_transfer`).

**⚠️ Important caveat:** The PRD-APPENDIX §A1 table describes the intended balance model. Section 8 documents gaps between this model and what the code currently implements.

### Transfer lifecycle — qty = 100, source WH On Hand starts at 2000

| Status | Source On Hand | Source Reserved | Source In Transit Out | Dest In Transit In | Dest On Hand | Code action |
|--------|---------------|-----------------|-----------------------|--------------------|--------------|-------------|
| DRAFT | 2000 | 0 | 0 | 0 | unchanged | No ledger entries |
| PENDING_REVIEW (PULL only) | 2000 | 0 | 0 | 0 | unchanged | No ledger entries (⚠ see §8 Gap #1) |
| PENDING_APPROVAL | 2000 | 0* | 0 | 0 | unchanged | No ledger entries (⚠ see §8 Gap #1) |
| APPROVED | **1900** | 0 | 0 | 0 | unchanged | `record_transaction(TRANSFER_OUT, -100)` at source |
| ISSUED | 1900 | 0 | **100** | 0 | unchanged | No ledger entries (⚠ see §8 Gap #2) |
| IN_TRANSIT | 1900 | 0 | 100 | **100** | unchanged | Status update only |
| PARTIALLY_RECEIVED | 1900 | 0 | varies | varies | unchanged | Partial TRANSFER_IN (not yet in code — ⚠ Gap #3) |
| RECEIVED | 1900 | 0 | **0** | **0** | **+100** | `record_transaction(TRANSFER_IN, +100)` at dest |
| COMPLETED | 1900 | 0 | 0 | 0 | 2000 (dest) | Status update only |

*PRD-APPENDIX §A1 shows Reserved = 100 at PENDING_APPROVAL. Current code does not write RESERVE entries — see Gap #1.

**CANCELLED from APPROVED/ADVISED:**  
`transition_transfer()` writes `RETURN` ledger entries (positive qty) at source to restore on_hand. On Hand returns to 2000.

**CANCELLED from DRAFT/PENDING states:**  
No ledger entries written. No balance impact.

### Key balance timing rules (from PRD-APPENDIX §A1)

```
Available = On Hand − Reserved − In Transit Out   (never stored, always computed)

In Transit Out is informational ONLY — it does NOT reduce Available.
On Hand was already reduced by TRANSFER_OUT at APPROVED.
Therefore: Available does not change between APPROVED and RECEIVED at source.
```

---

## SECTION 7 — Action Buttons Per Role Per Status

Source: `PRD-APPENDIX.md §A2`, `state_machine.py`, `transfer.py`.

**Facility scope principle:** WMs see action buttons ONLY for transfers involving their assigned facility. UUID comparisons use `.toLowerCase()` on both sides (CLAUDE.md §27).

---

### PULL transfers

| Status | Source WM | Dest WM | RM (not creator) | NM/TA |
|--------|-----------|---------|------------------|-------|
| DRAFT | View only | **Submit for Review**, Cancel | View only | View only |
| PENDING_REVIEW | View only | View only | **Send for Approval**, Reject, Cancel | View only |
| PENDING_APPROVAL | View only | View only | **Approve**, Reject, Cancel *(if RM is the required approver and not creator)* | **Approve**, Reject, Cancel *(if NM required and not creator)* |
| APPROVED | **Issue Stock**, Cancel | View only | Approve already done; View only | **Issue Stock**, Cancel |
| ISSUED | **Dispatch** | View only | View only | **Dispatch** |
| IN_TRANSIT | View only | **Partial Receive**, **Mark Received** | View only | View only |
| PARTIALLY_RECEIVED | View only | **Mark Received** | View only | View only |
| RECEIVED | View only | **Complete Transfer** | View only | View only |
| COMPLETED | View only | View only | View only | View only |
| REJECTED | View only | View only | View only | View only |
| CANCELLED | View only | View only | View only | View only |

**PENDING_APPROVAL detail:**  
The `approve_transfer` endpoint uses `can_approve = (not is_own_transfer) AND (caller_level <= required_authority_level)`. The frontend should show Approve only when `approval-info.can_approve = true`. The button label when `is_auto_approve=true` is: "✓ Approve (auto — within your authority)".

**PENDING_REVIEW — who sees "Send for Approval"?**  
PRD-APPENDIX §A2 shows "RM/NM/TA → Send for Approval, Reject, Cancel". The reviewer is whoever has `can_approve = true` for a PENDING_REVIEW → PENDING_APPROVAL transition. In practice this is RM (level 2) or higher, depending on configured tiers.

---

### PUSH transfers

| Status | Source WM/RM/NM | Dest WM | Notes |
|--------|----------------|---------|-------|
| DRAFT | **Submit**, Cancel | View only | Goes to PENDING_APPROVAL (no review step) |
| PENDING_APPROVAL | View only | View only | Required approver → **Approve**, Reject, Cancel |
| APPROVED | **Advise**, **Issue Stock**, Cancel | View only | ADVISED is optional (notify dest before dispatch) |
| ADVISED | **Issue Stock**, Cancel | View only | Dest notified; can flag issues back via Cancel |
| ISSUED | **Dispatch** | View only | |
| IN_TRANSIT | View only | **Partial Receive**, **Mark Received** | |
| PARTIALLY_RECEIVED | View only | **Mark Received** | |
| RECEIVED | View only | **Complete Transfer** | |
| COMPLETED / CANCELLED | View only | View only | Terminal |

---

### SISTER transfers

| Status | Source WM | Dest WM | RM/NM/TA |
|--------|-----------|---------|----------|
| DRAFT | **Submit** (→ PENDING_SOURCE_CONFIRM), Cancel | View only | View only |
| PENDING_SOURCE_CONFIRM | **Confirm Source**, Cancel | View only | View only |
| PENDING_DEST_CONFIRM | View only | **Confirm Dest** (→ PENDING_APPROVAL), **Reject** | View only |
| PENDING_APPROVAL | View only | View only | **Approve**, Reject, Cancel *(if required role and not creator)* |
| APPROVED | **Issue Stock** | View only | **Issue Stock** |
| ISSUED | **Dispatch** | View only | **Dispatch** |
| IN_TRANSIT | View only | **Partial Receive**, **Mark Received** | View only |
| RECEIVED | View only | **Complete Transfer** | View only |
| COMPLETED / REJECTED / CANCELLED | View only | View only | View only |

---

### ADJUSTMENT

| Status | Creator WM | Required Approver | Others |
|--------|------------|------------------|--------|
| DRAFT | **Submit** (→ PENDING_APPROVAL), Cancel | View only | View only |
| PENDING_APPROVAL | View only | **Approve**, Reject | View only |
| APPROVED | — | — | — (triggers `approve_adjustment()` → ledger entry → POSTED) |
| POSTED | View only | View only | View only (terminal) |
| REJECTED / CANCELLED | View only | View only | View only (terminal) |

**Awaiting approval display:**  
When `can_approve=false`: show `"Awaiting {required_role_display} approval — {reason}"`.  
The `reason` field from `ApprovalDecision` provides human-readable context (escalation reason, product minimum override reason, or standard quantity band description).

---

## SECTION 8 — Known Gaps or Issues

The following discrepancies were found between the specification (CLAUDE.md, PRD-APPENDIX) and the current implementation.

---

**Gap #1 — RESERVE ledger entries never written**  
**File:** `inventory_service.py: transition_transfer()`  
**Spec:** PRD-APPENDIX §A1 shows `Reserved = qty` at `PENDING_APPROVAL`. CLAUDE.md §27 states "Reserved shows at PENDING_REVIEW not DRAFT."  
**Current code:** `transition_transfer()` only writes `TRANSFER_OUT` (at APPROVED) and `TRANSFER_IN` (at RECEIVED). No `RESERVE` or `RELEASE` ledger entries are written at any status. `warehouse_stock.reserved` is therefore always 0 in current implementation.  
**Fix needed:** Write `RESERVE` entry (positive, `warehouse_id = from_warehouse_id`) when transitioning to `PENDING_APPROVAL`. Write `RELEASE` entry (negative) when transitioning to `APPROVED` (offset against the hard TRANSFER_OUT deduction) or `CANCELLED/REJECTED`.

---

**Gap #2 — `in_transit_out` / `in_transit_in` balances never updated**  
**File:** `inventory_service.py: dispatch_transfer()`, `receive_transfer()`  
**Spec:** PRD-APPENDIX §A1: `in_transit_out = qty` at ISSUED; `in_transit_in = qty` at IN_TRANSIT destination; both reset to 0 at RECEIVED.  
**Current code:** `dispatch_transfer()` writes no ledger entries. `warehouse_stock.in_transit_out` and `warehouse_stock.in_transit_in` are never updated by any current code path. The ISSUED and IN_TRANSIT rows in §A1 are not implemented.  
**Fix needed:** Either write informational ledger entries (e.g., `TRANSFER_PENDING_OUT`/`TRANSFER_PENDING_IN` types) at ISSUED/IN_TRANSIT to drive balance updates, or update `warehouse_stock.in_transit_out/in_transit_in` directly via a privileged session within `dispatch_transfer()` / `receive_transfer()`.

---

**Gap #3 — PARTIALLY_RECEIVED state has no ledger implementation**  
**File:** `inventory_service.py`  
**Spec:** CLAUDE.md §17 shows `PARTIALLY_RECEIVED` as a valid state in all transfer machines. PRD-APPENDIX §A2 shows "Partial Receive" button at IN_TRANSIT.  
**Current code:** `receive_transfer()` always writes FULL quantity `TRANSFER_IN` entries and advances to `RECEIVED`. There is no partial receive logic — no way to receive part of a transfer and leave it in `PARTIALLY_RECEIVED`.  
**Fix needed:** Add a `partial_receive_transfer()` method that accepts `{line_id: partial_qty}` map, writes TRANSFER_IN only for received quantities, and advances to `PARTIALLY_RECEIVED` instead of `RECEIVED`.

---

**Gap #4 — PUSH state machine missing `REJECTED` terminal state entry**  
**File:** `state_machine.py: PUSH_TRANSITIONS`  
**Issue:** `PUSH_TRANSITIONS` allows transitioning TO `REJECTED` (from `PENDING_APPROVAL`) but has no `"REJECTED": []` entry in the dict. When `validate_transition("PUSH", "REJECTED", any)` is called, `machine.get("REJECTED", [])` returns `[]` (silently treating REJECTED as a terminal state via the default), but this is implicit rather than explicit.  
**Fix needed:** Add `"REJECTED": []` to `PUSH_TRANSITIONS` for consistency and to prevent accidental future extension.

---

**Gap #5 — SISTER PENDING_DEST_CONFIRM missing CANCELLED transition**  
**File:** `state_machine.py: SISTER_TRANSITIONS`  
**Issue:** `"PENDING_DEST_CONFIRM": ["PENDING_APPROVAL", "REJECTED"]` — no CANCELLED path. If the destination WM wants to abandon (not reject) at this stage, the only option is REJECTED. This means the transfer ends as "REJECTED" even for an abandonment scenario, which pollutes reporting.  
**Fix needed (design decision):** Either add `"CANCELLED"` to `PENDING_DEST_CONFIRM` transitions if abandonment-vs-rejection semantics matter, or document that REJECTED is the correct terminal for dest-WM withdrawal.

---

**Gap #6 — Legacy `ApprovalService.route_approval()` uses inverted logic**  
**File:** `approval_service.py: ApprovalService.route_approval()`  
**Issue:** Legacy method uses `is_auto_approved = initiator_level >= required_level` with the OLD scale (SA=10). This is conceptually opposite to the new scale, has NO escalation logic (a WM can auto-approve their own PULL if the tier says WM), and does NOT call `product_approval_minimums`. Any caller still using `route_approval()` instead of `resolve_approval()` will produce incorrect results.  
**Current callers:** No callers of `route_approval()` were found in the reviewed files (`transfer.py`, `inventory_service.py` both use the new `resolve_approval()`). The legacy class is kept for backward compatibility but should be audited for remaining callsites in other services.  
**Fix needed:** Audit all services for `route_approval()` calls. Migrate to `resolve_approval()` or remove the legacy class once confirmed unused.

---

**Gap #7 — `resolve_approval()` does not query `approval_rule.product_id` rows**  
**File:** `approval_service.py: _query_threshold()`  
**Issue:** `_query_threshold()` only queries `product_id IS NULL` rows. Per PRD-APPENDIX §B9, the fallback chain is: product-level `approval_rule` rows → tenant-level `approval_rule` rows → org defaults. The new `resolve_approval()` covers product authority via `product_approval_minimums` (separate table, queried in Step 1), not via `approval_rule.product_id`. The two product-level override mechanisms coexist but are independent: `product_approval_minimums.min_authority_level` (new) vs `approval_rule WHERE product_id IS NOT NULL` (legacy, queried only by `ApprovalService.get_required_approver()`).  
**Fix needed (or document):** Either bridge the two mechanisms (query `approval_rule.product_id` in `resolve_approval()` Step 2 before the IS NULL query) or formally deprecate `approval_rule.product_id` in favour of `product_approval_minimums` and remove it from `ApprovalService`.

---

**Gap #8 — `approve_transfer` endpoint only targets `PENDING_APPROVAL → APPROVED`**  
**File:** `transfer.py: approve_transfer()`  
**Issue:** The `/transfers/{id}/approve` endpoint calls `svc.transition_transfer(user, transfer_id, "APPROVED")`. For PULL transfers in `PENDING_REVIEW`, this would raise HTTP 422 because `PENDING_REVIEW → APPROVED` is not a valid PULL transition. The review-to-approval step (`PENDING_REVIEW → PENDING_APPROVAL`) has no dedicated endpoint — it would have to go through the generic PATCH `/{id}` endpoint with `body.next_status = "PENDING_APPROVAL"`. This is correct but could confuse callers who assume `/approve` handles all pre-approval states.  
**Fix needed (documentation):** Clarify that the `approve` endpoint is only for `PENDING_APPROVAL → APPROVED`. Rename or add a `/review` endpoint for `PENDING_REVIEW → PENDING_APPROVAL` to make the intent explicit.

---

**Gap #9 — `resolve_approval()` called without `simple_mode` flag in `transfer.py`**  
**File:** `transfer.py: get_approval_info()` and `inventory_service.py: transition_transfer()`  
**Issue:** Both callers invoke `resolve_approval(..., simple_mode=True)` (the default). There is no mechanism for the caller to pass the tenant's actual mode (simple vs custom). The backend has no `tenants.approval_mode` column to query. This means Custom mode's PULL-fallback path (`not simple_mode and lookup_type != 'PULL'`) is **never activated** by current callers — all calls use simple_mode=True.  
**Fix needed:** Either add `tenants.approval_mode` (or read the presence of distinct per-type approval_rule rows as an implicit signal), and pass the correct `simple_mode` value at call sites.

---

**Gap #10 — NM escalation ceiling produces ambiguous reason string**  
**File:** `approval_service.py: resolve_approval()`  
**Issue:** When an NM (level 1) creates a transfer and any tier triggers escalation, `required_level = max(1, 1-1) = 1`. The escalation fires (`escalated=True`) but the level doesn't actually change. The `reason` string reads: `"Escalated: requester authority (level 1) cannot self-approve. Now requires National Manager / Tenant Admin (level 1)."` This is technically accurate but confusing — it claims escalation happened while stating the same role. The UI would need to display this carefully.  
**Fix needed:** When `escalated=True` but `required_level == threshold_level`, produce a clearer reason: `"Any {role_display} approval must come from a different user — not the creator."` This matches the PRD-APPENDIX §B8 multiple-NM routing note.

---

*End of report — 10 gaps identified. No code was changed.*
