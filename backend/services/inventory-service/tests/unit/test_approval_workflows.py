"""TestApprovalWorkflows — CLAUDE.md §21 / IMTS §6 approval matrix test cases.

15 tests, one per IMTS §6 scenario row, covering:
  Pull request routing  (3 scenarios)
  Push routing          (4 scenarios)
  Sister transfer       (4 scenarios)
  Damage / write-off    (4 scenarios)

Tests verify ApprovalService.route_approval() and, where the scenario
involves a state machine path, validate_transition() as well.

All tests are unit tests — no database connection required.  The DB is mocked
to return the approval rule result for each scenario.

Inline rule constants at the top of this file are AUTHORITATIVE for the IMTS
§6 approval matrix.  The seed script (scripts/seed_approval_rules.py) should
match these.

ADJUSTMENT_RULES uses 3 bands (WM / RM / TA) per the authoritative IMTS §6
matrix and the user-specified thresholds:
  0–99   → WM   (minor damage, WM self-approval)
  100–999 → RM  (mid-range, Regional Manager required)
  1000+  → TA   (large write-off, Tenant Admin / CEO required)
scripts/seed_approval_rules.py matches these bands as of Session 4.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.approval_service import ROLE_LEVEL, ApprovalDecision, ApprovalService
from services.state_machine import InvalidStateTransitionError, validate_transition

# ── Inline approval rule constants (authoritative IMTS §6 matrix) ────────────

TENANT_ID = "10000000-0000-0000-0000-000000000001"

# PULL: WH requests stock from RWH or MWH
PULL_RULES: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"),    Decimal("999.9999"),  "WM"),
    (Decimal("1000"), Decimal("4999.9999"), "RM"),
    (Decimal("5000"), None,                 "NM"),
]

# PUSH: MWH/RWH proactively sends stock downstream — always NM or above
PUSH_RULES: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"),    Decimal("4999.9999"), "NM"),
    (Decimal("5000"), None,                 "TA"),
]

# SISTER: peer WH ↔ WH lateral transfer
SISTER_RULES: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"),    Decimal("999.9999"), "WM"),
    (Decimal("1000"), None,               "RM"),
]

# ADJUSTMENT: damage / write-off / count variance — 3 bands (IMTS §6 / user spec)
ADJUSTMENT_RULES: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"),    Decimal("99.9999"),  "WM"),   # 0–99:    WM self-approval
    (Decimal("100"),  Decimal("999.9999"), "RM"),   # 100–999: RM required
    (Decimal("1000"), None,               "TA"),    # 1000+:   TA (CEO) required
]


# ── Mock DB helpers ───────────────────────────────────────────────────────────

def _mock_db(approver_role: str) -> AsyncMock:
    """Mock AsyncSession returning a single row with the given approver_role."""
    db   = AsyncMock()
    row  = MagicMock()
    row.__getitem__ = MagicMock(return_value=approver_role)
    db.execute = AsyncMock(
        return_value=MagicMock(fetchone=MagicMock(return_value=row))
    )
    return db


def _mock_db_no_rule() -> AsyncMock:
    """Mock AsyncSession that returns None (no matching approval rule)."""
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(fetchone=MagicMock(return_value=None))
    )
    return db


# ── Test class ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestApprovalWorkflows:
    """IMTS §6 approval matrices translated to test cases — one test per scenario row."""

    # ── Pull request routing ─────────────────────────────────────────────────

    async def test_pull_wh_to_rwh_sufficient_stock(self) -> None:
        """WM initiates PULL (qty=2000, RM band) → RM is the required approver.

        WM (level 6) < RM (level 7) — not auto-approved; transfer routes to
        PENDING_APPROVAL.  Once RM approves, the full PULL path to APPROVED
        is valid: DRAFT → PENDING_REVIEW → PENDING_APPROVAL → APPROVED.
        """
        svc      = ApprovalService(_mock_db("RM"))
        decision = await svc.route_approval(TENANT_ID, "PULL", Decimal("2000"), "WM")

        assert decision.required_role    == "RM"
        assert decision.is_auto_approved is False
        assert decision.next_status      == "PENDING_APPROVAL"

        # State machine: PULL mandatory review step must not be skipped
        validate_transition("PULL", "DRAFT",            "PENDING_REVIEW")
        validate_transition("PULL", "PENDING_REVIEW",   "PENDING_APPROVAL")
        validate_transition("PULL", "PENDING_APPROVAL", "APPROVED")

    async def test_pull_wh_to_rwh_insufficient_escalates(self) -> None:
        """qty ≥ 5000 escalates to NM — RM (level 7) cannot self-approve NM band.

        IMTS comment: 'RM escalates to LM; GM if > threshold'.
        GM = NM in canonical role codes (CLAUDE.md §24 role mapping table).
        LM here is the Logistics Manager who facilitates the escalation, but
        the required approver for the NM band is NM (level 8).
        """
        svc      = ApprovalService(_mock_db("NM"))
        decision = await svc.route_approval(TENANT_ID, "PULL", Decimal("6000"), "RM")

        assert decision.required_role    == "NM"
        assert decision.is_auto_approved is False   # RM (7) < NM (8)
        assert decision.next_status      == "PENDING_APPROVAL"

    async def test_pull_wh_to_mwh_direct_no_rwh(self) -> None:
        """WM initiates large direct PULL from MWH (no RWH in path) → NM required.

        LM (Logistics Manager, level 6) also cannot self-approve NM-band pulls.
        The absence of an intermediate RWH does not lower the approval threshold.
        """
        svc = ApprovalService(_mock_db("NM"))

        # WM cannot self-approve large pull from MWH
        wm_decision = await svc.route_approval(TENANT_ID, "PULL", Decimal("7000"), "WM")
        assert wm_decision.required_role    == "NM"
        assert wm_decision.is_auto_approved is False   # WM (6) < NM (8)

        # LM also cannot self-approve NM-band PULL (LM level = 6, same as WM)
        lm_decision = await svc.route_approval(TENANT_ID, "PULL", Decimal("7000"), "LM")
        assert lm_decision.is_auto_approved is False   # LM (6) < NM (8)

    # ── Push routing ─────────────────────────────────────────────────────────

    async def test_push_mwh_to_rwh_proactive(self) -> None:
        """LM initiates PUSH from MWH to RWH; NM must approve; ADVISED state reached.

        All PUSH transactions require NM (level 8) or above — LM (level 6) cannot
        self-approve.  After NM approval, the state machine reaches ADVISED so the
        destination RWH can flag capacity issues before stock is dispatched.
        """
        svc      = ApprovalService(_mock_db("NM"))
        decision = await svc.route_approval(TENANT_ID, "PUSH", Decimal("1000"), "LM")

        assert decision.required_role    == "NM"
        assert decision.is_auto_approved is False   # LM (6) < NM (8)
        assert decision.next_status      == "PENDING_APPROVAL"

        # PUSH state path after NM approves: APPROVED → ADVISED → ISSUED
        validate_transition("PUSH", "DRAFT",            "PENDING_APPROVAL")
        validate_transition("PUSH", "PENDING_APPROVAL", "APPROVED")
        validate_transition("PUSH", "APPROVED",         "ADVISED")
        validate_transition("PUSH", "ADVISED",          "ISSUED")

    async def test_push_mwh_to_wh_direct(self) -> None:
        """LM initiates PUSH from MWH directly to WH; NM approval required.

        Direct MWH → WH push (skipping RWH) uses the same PUSH routing as
        MWH → RWH — the destination tier does not affect who must approve.
        """
        svc      = ApprovalService(_mock_db("NM"))
        decision = await svc.route_approval(TENANT_ID, "PUSH", Decimal("500"), "LM")

        assert decision.required_role    == "NM"
        assert decision.is_auto_approved is False

        # ADVISED → ISSUED → IN_TRANSIT is the normal post-approval completion path
        validate_transition("PUSH", "ADVISED",  "ISSUED")
        validate_transition("PUSH", "ISSUED",   "IN_TRANSIT")
        validate_transition("PUSH", "IN_TRANSIT", "RECEIVED")

    async def test_push_rwh_to_wh_regional(self) -> None:
        """RM initiates PUSH from RWH to WH; NM still required — RM cannot self-approve.

        Even RM (level 7, regional authority) cannot self-approve PUSH transfers.
        All PUSH requires NM (level 8) oversight to prevent unilateral regional
        stock pushes that bypass national supply chain visibility.
        """
        svc      = ApprovalService(_mock_db("NM"))
        decision = await svc.route_approval(TENANT_ID, "PUSH", Decimal("1000"), "RM")

        assert decision.required_role    == "NM"
        assert decision.is_auto_approved is False   # RM (7) < NM (8)
        assert decision.next_status      == "PENDING_APPROVAL"

        # NM role is at level 8 — above RM (7) and LM (6)
        assert ROLE_LEVEL["NM"] > ROLE_LEVEL["RM"]
        assert ROLE_LEVEL["NM"] > ROLE_LEVEL["LM"]

    async def test_push_recipient_flag_pauses_dispatch(self) -> None:
        """Destination flags capacity issue from ADVISED state → CANCELLED (pauses dispatch).

        From ADVISED the destination can either accept (→ ISSUED) or flag a problem
        (→ CANCELLED).  The state machine must NOT allow ADVISED → APPROVED (backwards
        transition), ensuring the transfer cannot silently revert.
        """
        # Destination accepts — normal path
        validate_transition("PUSH", "ADVISED", "ISSUED")

        # Destination flags capacity/overstock issue → cancel dispatch
        validate_transition("PUSH", "ADVISED", "CANCELLED")

        # Cannot go backwards from ADVISED to APPROVED
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("PUSH", "ADVISED", "APPROVED")

        # Cannot skip ISSUED and go straight to IN_TRANSIT from ADVISED
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("PUSH", "ADVISED", "IN_TRANSIT")

    # ── Sister transfer routing ───────────────────────────────────────────────

    async def test_sister_same_region_both_agree(self) -> None:
        """Both WMs confirm small SISTER (qty=500); WM-level approval → auto-approved.

        Small SISTER transfers (< 1000 units) require WM-level approval.  Both source
        and destination WMs must confirm before the transfer reaches PENDING_APPROVAL.
        WM initiator is auto-approved (WM ≥ WM).  RM receives an outbox notification
        for visibility but is not the required blocking approver.
        """
        svc      = ApprovalService(_mock_db("WM"))
        decision = await svc.route_approval(TENANT_ID, "SISTER", Decimal("500"), "WM")

        assert decision.required_role    == "WM"
        assert decision.is_auto_approved is True   # WM (6) >= WM (6)
        assert decision.next_status      == "APPROVED"

        # Full SISTER state path — both confirms are mandatory steps
        validate_transition("SISTER", "DRAFT",                  "PENDING_SOURCE_CONFIRM")
        validate_transition("SISTER", "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM")
        validate_transition("SISTER", "PENDING_DEST_CONFIRM",   "PENDING_APPROVAL")
        validate_transition("SISTER", "PENDING_APPROVAL",       "APPROVED")

        # Source cannot skip to PENDING_DEST_CONFIRM directly
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("SISTER", "DRAFT", "PENDING_DEST_CONFIRM")

    async def test_sister_cross_region_both_agree(self) -> None:
        """Cross-region SISTER (qty=1500, RM band); WM cannot self-approve.

        Larger SISTER transfers (≥ 1000) require RM sign-off.  Even when both WMs
        agree across regions, WM (level 6) cannot self-approve RM-band (level 7).
        Both RMs and NM receive outbox notifications for cross-region visibility,
        but the blocking approver is RM.
        """
        svc      = ApprovalService(_mock_db("RM"))
        decision = await svc.route_approval(TENANT_ID, "SISTER", Decimal("1500"), "WM")

        assert decision.required_role    == "RM"
        assert decision.is_auto_approved is False   # WM (6) < RM (7)
        assert decision.next_status      == "PENDING_APPROVAL"

    async def test_sister_rwh_cross_region(self) -> None:
        """RM(src) and RM(dst) confirm cross-region RWH SISTER; RM self-approves.

        When both sides are RWH-level (managed by RM), and qty is in the RM band,
        the RM initiator can self-approve (RM ≥ RM).  NM receives an outbox
        notification for national visibility but is not a blocking approver.
        """
        svc      = ApprovalService(_mock_db("RM"))
        decision = await svc.route_approval(TENANT_ID, "SISTER", Decimal("1500"), "RM")

        assert decision.required_role    == "RM"
        assert decision.is_auto_approved is True    # RM (7) >= RM (7)
        assert decision.next_status      == "APPROVED"

        # RM is the approver level — verify the hierarchy invariant
        assert ROLE_LEVEL["RM"] > ROLE_LEVEL["WM"]
        assert ROLE_LEVEL["NM"] > ROLE_LEVEL["RM"]

    async def test_sister_rejected_by_destination(self) -> None:
        """Destination WM declines at PENDING_DEST_CONFIRM → REJECTED (terminal).

        The destination manager's refusal terminates the transfer.  REJECTED is a
        terminal state — no further transitions are permitted from it.
        """
        # Destination WM declines
        validate_transition("SISTER", "PENDING_DEST_CONFIRM", "REJECTED")

        # REJECTED is terminal — no state change possible after rejection
        for next_state in ("PENDING_APPROVAL", "APPROVED", "ISSUED",
                           "IN_TRANSIT", "RECEIVED", "COMPLETED", "DRAFT"):
            with pytest.raises(InvalidStateTransitionError,
                               match=r"SISTER.*REJECTED"):
                validate_transition("SISTER", "REJECTED", next_state)

    # ── Damage / write-off routing ────────────────────────────────────────────

    async def test_damage_within_wm_limit_auto_approved(self) -> None:
        """ADJUSTMENT qty=50 (WM band, < 100) → WM auto-approves.

        Minor damage or count variances below the WM self-approval threshold
        are auto-approved.  WM initiator (level 6) >= WM required (level 6).
        The adjustment state machine proceeds directly to POSTED.

        Note (CLAUDE.md §24 Business Rule #13): audit_log is written for ALL
        adjustments including auto-approved ones.  is_auto_approved=True means
        the approval check passed; it does not suppress the audit trail.
        """
        svc      = ApprovalService(_mock_db("WM"))
        decision = await svc.route_approval(TENANT_ID, "ADJUSTMENT", Decimal("50"), "WM")

        assert decision.required_role    == "WM"
        assert decision.is_auto_approved is True
        assert decision.next_status      == "APPROVED"

        # ADJUSTMENT state machine: DRAFT → PENDING_APPROVAL → APPROVED → POSTED
        validate_transition("ADJUSTMENT", "DRAFT",            "PENDING_APPROVAL")
        validate_transition("ADJUSTMENT", "PENDING_APPROVAL", "APPROVED")
        validate_transition("ADJUSTMENT", "APPROVED",         "POSTED")

        # POSTED is terminal — no transit states exist for adjustments
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("ADJUSTMENT", "POSTED", "COMPLETED")

    async def test_damage_exceeds_wm_limit_routes_to_rm(self) -> None:
        """ADJUSTMENT qty=500 (RM band, 100–999) → RM required; WM cannot self-approve.

        Adjustments at or above 100 units exceed the WM self-approval limit.
        RM (level 7) must review before the adjustment is posted to the ledger.
        qty=500 is clearly in the RM band (100–999) — above WM limit but below
        the 1000-unit threshold that requires TA.
        """
        svc      = ApprovalService(_mock_db("RM"))
        decision = await svc.route_approval(TENANT_ID, "ADJUSTMENT", Decimal("500"), "WM")

        assert decision.required_role    == "RM"
        assert decision.is_auto_approved is False   # WM (6) < RM (7)
        assert decision.next_status      == "PENDING_APPROVAL"

    async def test_damage_exceeds_limit_final_ta(self) -> None:
        """ADJUSTMENT qty=1200 (TA band, ≥ 1000) → TA (CEO-equivalent) required.

        Large write-offs at or above 1000 units require Tenant Admin approval.
        TA is the highest tenant-scoped role (level 9).  NM (level 8) cannot
        self-approve TA-band adjustments.
        """
        svc      = ApprovalService(_mock_db("TA"))
        decision = await svc.route_approval(TENANT_ID, "ADJUSTMENT", Decimal("1200"), "NM")

        assert decision.required_role    == "TA"
        assert decision.is_auto_approved is False   # NM (8) < TA (9)
        assert decision.next_status      == "PENDING_APPROVAL"

        # TA is the ceiling for tenant-scoped approvals
        assert ROLE_LEVEL["TA"] > ROLE_LEVEL["NM"]

    async def test_mwh_damage_exceeds_limit_to_ta(self) -> None:
        """LM initiates large MWH damage write-off (qty=1500); TA approval required.

        LM (Logistics Manager, level 6) manages the Main Warehouse.  When a
        large write-off (≥ 1000) is initiated at MWH, TA sign-off is required.
        LM is three levels below TA — cannot self-approve.

        The multi-step escalation path (LM initiates → NM advisory review →
        TA final approval) is captured through approval_order in the rule table.
        This test verifies the highest required approver for the TA-band scenario.
        """
        svc      = ApprovalService(_mock_db("TA"))
        decision = await svc.route_approval(TENANT_ID, "ADJUSTMENT", Decimal("1500"), "LM")

        assert decision.required_role    == "TA"
        assert decision.is_auto_approved is False   # LM (6) < TA (9)
        assert decision.next_status      == "PENDING_APPROVAL"

        # Role level chain: LM < NM < TA (each level two steps below TA)
        assert ROLE_LEVEL["LM"] < ROLE_LEVEL["NM"] < ROLE_LEVEL["TA"]

    # ── Missing rule guard ────────────────────────────────────────────────────

    async def test_get_required_approver_falls_back_to_org_type_default(self) -> None:
        """When no DB rule matches, get_required_approver falls back to the
        hardcoded org-type defaults (_ORG_TYPE_DEFAULTS) instead of raising.

        PULL qty=500 is in the WM band (0–999) of the default rules.
        PROMPT C §fallback: Level 3 fallback never raises for valid tx types.
        """
        svc = ApprovalService(_mock_db_no_rule())

        role = await svc.get_required_approver(TENANT_ID, "PULL", Decimal("500"))
        assert role == "WM"

    async def test_org_type_default_raises_for_unknown_tx_type(self) -> None:
        """ValueError is still raised when the transaction_type is unrecognised —
        the org-type defaults only cover PULL, PUSH, ADJUSTMENT, SISTER."""
        svc = ApprovalService(_mock_db_no_rule())

        with pytest.raises(ValueError, match="No default approval rule"):
            await svc.get_required_approver(TENANT_ID, "UNKNOWN_TYPE", Decimal("500"))

    # ── resolve_approval() 3-step resolution tests ───────────────────────────

    async def test_resolve_approval_product_min_wins(self) -> None:
        """When product authority floor (level 2 = RM) is tighter than the qty band
        (level 4 = WM), required_authority_level = min(2, 4) = 2.

        product_min=2 overrides threshold_level=4 because lower = higher authority.
        is_auto_approved must be False (product override disables auto-approve).
        """
        from services.approval_service import resolve_approval

        PRODUCT = "pppppppp-0000-0000-0000-000000000001"
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=(2,))),              # pam → min_level=2
            MagicMock(fetchone=MagicMock(return_value=("WM", 4, True, []))),  # band → WM level 4
        ])

        decision = await resolve_approval(
            db, TENANT_ID, "PULL", Decimal("50"), product_id=PRODUCT
        )

        assert decision.required_authority_level == 2, (
            "product_min=2 must win over threshold=4: min(2,4)=2"
        )
        assert decision.is_auto_approved is False, (
            "auto_approve must be False when product override is in effect"
        )

    async def test_resolve_approval_qty_threshold_wins(self) -> None:
        """Without a product override, the quantity-band threshold (level 2 = RM)
        determines required_authority_level directly."""
        from services.approval_service import resolve_approval

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("RM", 2, False, [])))
        )

        decision = await resolve_approval(db, TENANT_ID, "PULL", Decimal("2000"))

        assert decision.required_authority_level == 2
        assert decision.required_role == "RM"
        assert decision.is_auto_approved is False

    async def test_resolve_approval_higher_wins(self) -> None:
        """When product_min=1 (NM/TA) is more restrictive than threshold=2 (RM),
        required_authority_level = min(1, 2) = 1."""
        from services.approval_service import resolve_approval

        PRODUCT = "pppppppp-0000-0000-0000-000000000002"
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=(1,))),              # pam → min_level=1
            MagicMock(fetchone=MagicMock(return_value=("RM", 2, False, []))),  # band → RM level 2
        ])

        decision = await resolve_approval(
            db, TENANT_ID, "PULL", Decimal("2000"), product_id=PRODUCT
        )

        assert decision.required_authority_level == 1, (
            "product_min=1 must win over threshold=2: min(1,2)=1"
        )
        assert decision.is_auto_approved is False

    async def test_sister_shares_pull_tiers(self) -> None:
        """SISTER transfers use PULL quantity bands — _query_threshold() is called
        with tx_type='PULL' even when transaction_type='SISTER'."""
        from services.approval_service import resolve_approval

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("WM", 4, False, [])))
        )

        await resolve_approval(db, TENANT_ID, "SISTER", Decimal("100"))

        # Verify that the threshold query used 'PULL' not 'SISTER'
        assert db.execute.await_count == 1, "no product_id → exactly one DB call"
        call_params = db.execute.call_args_list[0].args[1]
        assert call_params["tx_type"] == "PULL", (
            "SISTER must look up PULL bands, not SISTER bands"
        )

    # ── Regression tests (PROMPT 3 — approval UI + routing) ──────────────────

    async def test_wm_cannot_approve_above_threshold(self) -> None:
        """Regression: WM initiator cannot auto-approve when qty falls in RM band.

        Authority level scale: WM=4, RM=2, NM/TA=1.  Lower = higher authority.
        can_approve = (caller_level <= required_level), so WM(4) cannot approve
        a band that requires RM(2).  resolve_approval must return is_auto_approved=False.

        Protects against regressions where caller_level was compared with the wrong
        direction (e.g. >=) causing WM to self-approve above-threshold transfers.
        """
        from services.approval_service import resolve_approval

        # Band returns RM (authority_level=2), auto_approve=False, no product override
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("RM", 2, False, [])))
        )

        # WM initiates a PULL in the RM quantity band (qty=2000)
        decision = await resolve_approval(db, TENANT_ID, "PULL", Decimal("2000"))

        assert decision.required_authority_level == 2, (
            "RM-band transfer must require authority level 2"
        )
        assert decision.required_role == "RM"
        assert decision.is_auto_approved is False, (
            "WM (level 4) must not auto-approve RM-band (level 2) transfer"
        )
        assert decision.next_status == "PENDING_APPROVAL", (
            "Non-auto-approved transfer must route to PENDING_APPROVAL"
        )

    async def test_auto_approve_notifies_rm(self) -> None:
        """Regression: auto-approve decision forwards notify_levels from the band rule.

        When a band has auto_approve=True and notify_levels=[2] (RM tier), the
        ApprovalDecision must include notify_levels=[2] so the outbox writer can
        dispatch AutoApprovalNotice events to the correct managers.

        Protects against regressions where notify_levels was dropped from the
        decision object or not forwarded by resolve_approval().
        """
        from services.approval_service import resolve_approval

        # Band: auto_approve=True, notify_levels=[2] (notify RM when auto-approved)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("WM", 4, True, [2])))
        )

        decision = await resolve_approval(db, TENANT_ID, "PULL", Decimal("50"))

        assert decision.is_auto_approved is True, (
            "Band with auto_approve=True and no product override must be auto-approved"
        )
        assert decision.next_status == "APPROVED"
        assert 2 in decision.notify_levels, (
            "notify_levels=[2] from band rule must be forwarded in the decision "
            "so AutoApprovalNotice events reach RM (level 2)"
        )

    async def test_product_min_overrides_threshold(self) -> None:
        """Regression: product-level authority floor disables auto-approve even when
        the quantity band is marked auto_approve=True.

        Scenario: WM (level 4) requests a small PULL (qty=50) that is in the WM
        auto-approve band (auto_approve=True, authority_level=4).  But the product
        has min_authority_level=2 (RM required).  resolve_approval must:
          1. Set required_authority_level = min(2, 4) = 2
          2. Set is_auto_approved = False (product override disables auto-approve)
          3. Set next_status = PENDING_APPROVAL

        Protects against regressions where the product-level floor was fetched but
        not applied to the auto-approve flag, allowing low-quantity transfers to
        bypass RM review on controlled products.
        """
        from services.approval_service import resolve_approval

        PRODUCT = "pppppppp-0000-0000-0000-000000000099"
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=(2,))),               # pam → min_level=2
            MagicMock(fetchone=MagicMock(return_value=("WM", 4, True, []))),  # band → WM, auto=True
        ])

        decision = await resolve_approval(
            db, TENANT_ID, "PULL", Decimal("50"), product_id=PRODUCT
        )

        assert decision.required_authority_level == 2, (
            "product_min=2 must override band level=4: min(2,4)=2"
        )
        assert decision.is_auto_approved is False, (
            "product override must disable auto-approve even when band says auto_approve=True"
        )
        assert decision.next_status == "PENDING_APPROVAL", (
            "product override must route to PENDING_APPROVAL, not APPROVED"
        )

    async def test_sister_shares_pull_tiers_in_ui(self) -> None:
        """Regression: SISTER UI note 'shares these tiers with PULL' is backed by
        backend logic — resolve_approval() for SISTER must query PULL bands.

        This test verifies the backend contract that the SISTER approval tab in org-setup
        (which shows 'SISTER transfers share these tiers with PULL') correctly mirrors
        the backend behaviour: quantity-band lookup always uses tx_type='PULL' for SISTER.

        Specifically verifies:
          - The DB query parameter tx_type='PULL' (not 'SISTER')
          - The decision's required_authority_level matches the PULL band
          - A qty=1500 SISTER (PULL RM band) routes to PENDING_APPROVAL for WM initiator
        """
        from services.approval_service import resolve_approval

        # RM band: authority_level=2, auto_approve=False (mirrors PULL 1000–4999 band)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("RM", 2, False, [])))
        )

        decision = await resolve_approval(db, TENANT_ID, "SISTER", Decimal("1500"))

        # Backend must query PULL bands for SISTER (the UI 'shares PULL tiers' invariant)
        assert db.execute.await_count == 1, "no product_id → exactly one DB call"
        call_params = db.execute.call_args_list[0].args[1]
        assert call_params["tx_type"] == "PULL", (
            "SISTER must query PULL bands — backend contract backing the UI note "
            "'SISTER transfers share these tiers with PULL'"
        )

        # Verify the routing result is correct (WM cannot self-approve RM-band SISTER)
        assert decision.required_authority_level == 2
        assert decision.required_role == "RM"
        assert decision.is_auto_approved is False
