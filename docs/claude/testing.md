## 21. Testing Requirements

### 15 required permission test cases per action

```python
class TestInventoryReceivePermissions:
    async def test_01_rbac_happy_path(self):       ...  # WM + valid context → 201
    async def test_02_rbac_deny_wrong_role(self):  ...  # AU → 403 RBAC_DENIED
    async def test_03_abac_wrong_tenant(self):     ...  # Correct role, wrong tenant → 403
    async def test_04_abac_wrong_region(self):     ...  # Correct role, wrong region → 403
    async def test_05_abac_wrong_warehouse(self):  ...  # Correct role, wrong warehouse → 403
    async def test_06_abac_ownership(self):        ...  # Wrong owner_id → 403
    async def test_07_conditional_below(self):     ...  # WM below threshold → 200 auto-approved
    async def test_08_conditional_above(self):     ...  # WM above threshold → 202 pending RM
    async def test_09_auditor_read_only(self):     ...  # AU write attempt → 403
    async def test_10_read_only_grant(self):       ...  # R-grant write attempt → 403
    async def test_11_audit_log_allow(self):       ...  # Success → GRANTED in audit_logs
    async def test_12_audit_log_deny(self):        ...  # Failure → DENIED in audit_logs
    async def test_13_rls_cross_tenant(self):      ...  # Tenant A cannot read Tenant B → empty
    async def test_14_jwt_expired(self):           ...  # Expired token → 401
    async def test_15_sys_only_action(self):       ...  # User calls ai:model_run → 403
```

### Additional required test suites

```python
class TestOutboxPattern:
    async def test_outbox_written_in_same_transaction(self): ...
    async def test_worker_idempotent_on_already_processed(self): ...
    async def test_failed_row_retried_with_backoff(self): ...

class TestDispatch:
    async def test_fefo_nearest_expiry_selected(self): ...
    async def test_fefo_cascades_across_lots(self): ...
    async def test_fefo_auto_enforced_when_expiry_tracking_active(self): ...
    async def test_fefo_override_requires_permission_and_reason(self): ...
    async def test_override_written_to_dispatch_override_logs(self): ...

class TestLocalization:
    async def test_oromifa_pack_loads_without_error(self): ...
    async def test_user_locale_overrides_tenant_default(self): ...
    async def test_missing_key_returns_key_not_empty_string(self): ...

class TestApprovalWorkflows:
    """IMTS §6 approval matrices translated to test cases — one test per scenario row."""
    # Pull request routing
    async def test_pull_wh_to_rwh_sufficient_stock(self):       ...  # WM initiates → RM approves → APPROVED
    async def test_pull_wh_to_rwh_insufficient_escalates(self): ...  # RM escalates to LM; GM if > threshold
    async def test_pull_wh_to_mwh_direct_no_rwh(self):         ...  # WM → LM → GM if large qty
    # Push routing
    async def test_push_mwh_to_rwh_proactive(self):             ...  # LM initiates → NM approves → ADVISED to RWH
    async def test_push_mwh_to_wh_direct(self):                 ...  # LM initiates → NM approves → ADVISED to WH
    async def test_push_rwh_to_wh_regional(self):               ...  # RM initiates → LM advisory → ADVISED to WH
    async def test_push_recipient_flag_pauses_dispatch(self):   ...  # Destination flags → status returns to APPROVED
    # Sister transfer routing
    async def test_sister_same_region_both_agree(self):         ...  # WM(src) → WM(dst) agree → RM notified
    async def test_sister_cross_region_both_agree(self):        ...  # WM(src) → WM(dst) agree → both RMs + LM notified
    async def test_sister_rwh_cross_region(self):               ...  # RM(src) → RM(dst) agree → LM notified
    async def test_sister_rejected_by_destination(self):        ...  # Destination WM declines → REJECTED
    # Damage / write-off routing
    async def test_damage_within_wm_limit_auto_approved(self):  ...  # Auto-approved; audit log created
    async def test_damage_exceeds_wm_limit_routes_to_rm(self):  ...  # RM first approval required
    async def test_damage_exceeds_limit_final_ta(self):         ...  # TA (CEO) final approval
    async def test_mwh_damage_exceeds_limit_to_ta(self):        ...  # LM initiates → NM → TA if exceeds

class TestIMTSStateMachines:
    """Type-specific state machine enforcement — PULL, PUSH, SISTER, DAMAGE."""
    async def test_pull_cannot_skip_pending_review(self):       ...  # DRAFT → PENDING_APPROVAL raises 422
    async def test_push_has_no_pending_review_state(self):      ...  # PUSH DRAFT → PENDING_APPROVAL valid
    async def test_push_advised_state_reachable(self):          ...  # APPROVED → ADVISED valid for PUSH
    async def test_sister_requires_source_confirm_first(self):  ...  # DRAFT → PENDING_DEST_CONFIRM raises 422
    async def test_partial_receipt_intermediate_state(self):    ...  # IN_TRANSIT → PARTIALLY_RECEIVED valid
    async def test_adjustment_ends_at_posted_not_received(self):...  # APPROVED → POSTED; POSTED is terminal

class TestMultiSourceSplitRequest:
    """IMTS split request — each leg is an independent transaction with own idempotency key."""
    async def test_split_legs_have_unique_idempotency_keys(self): ...
    async def test_split_legs_share_parent_transfer_id(self):     ...
    async def test_parent_status_derived_from_legs(self):         ...  # parent not directly settable
    async def test_one_leg_received_other_in_transit(self):       ...  # PARTIALLY_RECEIVED state correct

class TestIMTSAlerts:
    """IMTS threshold alert types beyond basic low-stock."""
    async def test_24h_escalation_fires_if_no_action(self):      ...  # Celery beat task fires to RM + LM
    async def test_multiple_whs_below_min_aggregate_alert(self):  ...  # Regional aggregate fires to RM
    async def test_in_transit_overdue_alert_fires(self):          ...  # estimated_arrival_date past X days
```

### Backend testing lessons (2026-10-10)

- **Contract-stage fixture is autouse.** `backend/conftest.py`'s
  `_default_contract_stage_active` patches `shared.billing.contract_stage.
  get_tenant_contract_stage()` to always return `ACTIVE` for every test, so
  `require_permission()`'s `READ_ONLY` gate never issues its own
  `db.execute()` and shift a mocked db's `execute.side_effect` queue out
  from under a pre-existing test. A test that specifically wants to
  exercise `EXPIRING`/`GRACE`/`READ_ONLY` behaviour patches
  `get_tenant_contract_stage` explicitly inside its own `with patch(...)`
  block — that patch wins for its duration and does not need to restore
  the autouse default afterward.
- **tenant-service has no HTTP test client yet.** Its tests call router
  handler functions directly (no `TestClient`/`AsyncClient`/`httpx`
  anywhere under `backend/services/tenant-service/tests/`) — write new
  tests the same way (handler-level, mocked `db`/`user`), not against a
  running app instance.
- **Run the full unfiltered suite, not `-m unit`.** Restated from CLAUDE.md
  §7: `pytest backend/ --cov=backend` is the real gate. `-m unit` silently
  skips every unmarked test file, which has hidden whole suites before
  (e.g. all of `backend/shared/billing/tests/`).

### Frontend testing lessons (2026-10-10)

- **`t()` is non-reactive.** `frontend/src/lib/i18n.ts`'s `t()` reads a
  module-level `translations` object, not React state — switching locale
  (`setLocale()`/`loadLocale()`) does not by itself re-render components
  already on screen. Playwright specs that switch locale mid-test must
  `page.reload()` after setting it (see `s12-legal.spec.ts`'s Amharic
  case) rather than asserting translated text right after the switch.
- **Block the service worker when intercepting requests.** A spec that
  uses `page.route()` to mock an API response (e.g. to force
  `402 CONTRACT_EXPIRED_READ_ONLY` or a `GRACE`/`READ_ONLY` banner without
  a real expired tenant) must call `test.use({ serviceWorkers: "block" })`
  for that file — otherwise the PWA service worker can serve its own
  cached/offline response before Playwright's route interception ever
  sees the request. See `p4-contract-renewal.spec.ts`,
  `p5-write-guard.spec.ts`, `p6-settings-guard.spec.ts`.
- **Playwright runs in the foreground only** (CLAUDE.md §7/§8) — a
  background run does not survive a session pause, and its pass/fail
  result and console-error output must be read directly, not assumed.

