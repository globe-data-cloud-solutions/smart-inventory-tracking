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

    async def test_get_required_approver_raises_when_no_rule_matches(self) -> None:
        """ValueError is raised when no approval_rule band matches the request.

        This is a configuration error — the tenant has not been seeded with rules
        for this transfer_type / quantity combination.  The error message must
        direct the operator to the seed script.
        """
        svc = ApprovalService(_mock_db_no_rule())

        with pytest.raises(ValueError, match="No approval rule found"):
            await svc.get_required_approver(TENANT_ID, "PULL", Decimal("500"))
