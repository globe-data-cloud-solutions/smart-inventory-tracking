"""TestApprovalWorkflows — CLAUDE.md §21 / IMTS §6 approval matrix test cases.

15 tests, one per IMTS §6 scenario row, covering:
  Pull request routing  (3 scenarios)
  Push routing          (4 scenarios)
  Sister transfer       (4 scenarios)
  Damage / write-off    (4 scenarios)

All tests call the module-level resolve_approval() function.
ApprovalService and route_approval() have been removed (Gap 3 refactor).

All tests are unit tests — no database connection required.  The DB is mocked
to return the approval rule band for each scenario.

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

from services.approval_service import ROLE_AUTHORITY_LEVEL, resolve_approval
from services.state_machine import InvalidStateTransitionError, validate_transition

# ── Inline approval rule constants (authoritative IMTS §6 matrix) ────────────

TENANT_ID = "10000000-0000-0000-0000-000000000001"

# PULL: WH requests stock from RWH or MWH
PULL_RULES: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"), Decimal("999.9999"), "WM"),
    (Decimal("1000"), Decimal("4999.9999"), "RM"),
    (Decimal("5000"), None, "NM"),
]

# PUSH: MWH/RWH proactively sends stock downstream — always NM or above
PUSH_RULES: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"), Decimal("4999.9999"), "NM"),
    (Decimal("5000"), None, "TA"),
]

# SISTER: peer WH ↔ WH lateral transfer
SISTER_RULES: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"), Decimal("999.9999"), "WM"),
    (Decimal("1000"), None, "RM"),
]

# ADJUSTMENT: damage / write-off / count variance — 3 bands (IMTS §6 / user spec)
ADJUSTMENT_RULES: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"), Decimal("99.9999"), "WM"),  # 0–99:    WM self-approval
    (Decimal("100"), Decimal("999.9999"), "RM"),  # 100–999: RM required
    (Decimal("1000"), None, "TA"),  # 1000+:   TA (CEO) required
]


# ── Mock DB helpers ───────────────────────────────────────────────────────────


def _threshold_db(role: str, level: int, auto: bool = False) -> AsyncMock:
    """Mock DB for resolve_approval() returning a single threshold band row.

    Row format expected by _query_threshold():
      (approver_role, authority_level, auto_approve, notify_levels)
    """
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(fetchone=MagicMock(return_value=(role, level, auto, [])))
    )
    return db


def _mock_db_no_rule() -> AsyncMock:
    """Mock AsyncSession that returns None (no matching approval rule)."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    return db


# ── Test class ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestApprovalWorkflows:
    """IMTS §6 approval matrices translated to test cases — one test per scenario row."""

    # ── Pull request routing ─────────────────────────────────────────────────

    async def test_pull_wh_to_rwh_sufficient_stock(self) -> None:
        """WM initiates PULL (qty=2000, RM band) → RM is the required approver.

        RM band is not auto-approve (auto_approve=False in rule config).
        Transfer routes to PENDING_APPROVAL.
        PULL mandatory review: DRAFT → PENDING_REVIEW → PENDING_APPROVAL → APPROVED.
        """
        decision = await resolve_approval(
            _threshold_db("RM", 2, auto=False), TENANT_ID, "PULL", Decimal("2000")
        )

        assert decision.required_role == "RM"
        assert decision.required_authority_level == 2
        assert decision.is_auto_approved is False
        assert decision.next_status == "PENDING_APPROVAL"

        # State machine: PULL mandatory review step must not be skipped
        validate_transition("PULL", "DRAFT", "PENDING_REVIEW")
        validate_transition("PULL", "PENDING_REVIEW", "PENDING_APPROVAL")
        validate_transition("PULL", "PENDING_APPROVAL", "APPROVED")

    async def test_pull_wh_to_rwh_insufficient_escalates(self) -> None:
        """qty ≥ 5000 routes to NM band — NM band is not auto-approve.

        IMTS comment: 'RM escalates to LM; GM if > threshold'.
        GM = NM in canonical role codes (CLAUDE.md §24 role mapping table).
        """
        decision = await resolve_approval(
            _threshold_db("NM", 1, auto=False), TENANT_ID, "PULL", Decimal("6000")
        )

        assert decision.required_role == "NM"
        assert decision.required_authority_level == 1
        assert decision.is_auto_approved is False
        assert decision.next_status == "PENDING_APPROVAL"

    async def test_pull_wh_to_mwh_direct_no_rwh(self) -> None:
        """Large PULL from MWH (qty=7000) → NM band required; NM band not auto-approve.

        NM band (authority_level=1) applies regardless of whether an intermediate
        RWH exists in the supply path.
        """
        # Both WM and LM requesters get the same routing for NM-band PULL
        for requester_level in (4, 3):  # WM=4, LM=3
            decision = await resolve_approval(
                _threshold_db("NM", 1, auto=False),
                TENANT_ID,
                "PULL",
                Decimal("7000"),
                requester_authority_level=requester_level,
            )
            assert decision.required_role == "NM"
            assert decision.is_auto_approved is False
            assert decision.required_authority_level == 1

    # ── Push routing ─────────────────────────────────────────────────────────

    async def test_push_mwh_to_rwh_proactive(self) -> None:
        """LM initiates PUSH from MWH to RWH; NM band required; not auto-approve.

        All PUSH transactions use the NM-or-above band (auto_approve=False).
        After NM approval, the state machine reaches ADVISED so the destination
        RWH can flag capacity issues before stock is dispatched.
        """
        decision = await resolve_approval(
            _threshold_db("NM", 1, auto=False), TENANT_ID, "PUSH", Decimal("1000")
        )

        assert decision.required_role == "NM"
        assert decision.required_authority_level == 1
        assert decision.is_auto_approved is False
        assert decision.next_status == "PENDING_APPROVAL"

        # PUSH state path after NM approves: APPROVED → ADVISED → ISSUED
        validate_transition("PUSH", "DRAFT", "PENDING_APPROVAL")
        validate_transition("PUSH", "PENDING_APPROVAL", "APPROVED")
        validate_transition("PUSH", "APPROVED", "ADVISED")
        validate_transition("PUSH", "ADVISED", "ISSUED")

    async def test_push_mwh_to_wh_direct(self) -> None:
        """LM initiates PUSH from MWH directly to WH; NM band required.

        Direct MWH → WH push (skipping RWH) uses the same NM-band routing —
        the destination tier does not affect the required approver.
        """
        decision = await resolve_approval(
            _threshold_db("NM", 1, auto=False), TENANT_ID, "PUSH", Decimal("500")
        )

        assert decision.required_role == "NM"
        assert decision.is_auto_approved is False

        # ADVISED → ISSUED → IN_TRANSIT is the normal post-approval completion path
        validate_transition("PUSH", "ADVISED", "ISSUED")
        validate_transition("PUSH", "ISSUED", "IN_TRANSIT")
        validate_transition("PUSH", "IN_TRANSIT", "RECEIVED")

    async def test_push_rwh_to_wh_regional(self) -> None:
        """RM initiates PUSH from RWH to WH; NM band required.

        All PUSH uses the NM-or-above band regardless of initiator role.
        NM has a lower authority level number (1) than RM (2) and LM (3),
        meaning NM has higher authority than both.
        """
        decision = await resolve_approval(
            _threshold_db("NM", 1, auto=False), TENANT_ID, "PUSH", Decimal("1000")
        )

        assert decision.required_role == "NM"
        assert decision.required_authority_level == 1
        assert decision.is_auto_approved is False
        assert decision.next_status == "PENDING_APPROVAL"

        # NM (1) has higher authority than RM (2) and LM (3) — lower number wins
        assert ROLE_AUTHORITY_LEVEL["NM"] < ROLE_AUTHORITY_LEVEL["RM"]
        assert ROLE_AUTHORITY_LEVEL["NM"] < ROLE_AUTHORITY_LEVEL["LM"]

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
        """Both WMs confirm small SISTER (qty=500); WM band is auto-approve.

        Small SISTER transfers (< 1000 units) use the WM band (auto_approve=True).
        Both source and destination WMs must confirm before PENDING_APPROVAL.
        RM receives an outbox notification for visibility but is not the blocking approver.

        Note: SISTER always looks up PULL quantity bands (see test_sister_shares_pull_tiers).
        """
        decision = await resolve_approval(
            _threshold_db("WM", 4, auto=True), TENANT_ID, "SISTER", Decimal("500")
        )

        assert decision.required_role == "WM"
        assert decision.required_authority_level == 4
        assert decision.is_auto_approved is True
        assert decision.next_status == "APPROVED"

        # Full SISTER state path — both confirms are mandatory steps
        validate_transition("SISTER", "DRAFT", "PENDING_SOURCE_CONFIRM")
        validate_transition("SISTER", "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM")
        validate_transition("SISTER", "PENDING_DEST_CONFIRM", "PENDING_APPROVAL")
        validate_transition("SISTER", "PENDING_APPROVAL", "APPROVED")

        # Source cannot skip to PENDING_DEST_CONFIRM directly
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("SISTER", "DRAFT", "PENDING_DEST_CONFIRM")

    async def test_sister_cross_region_both_agree(self) -> None:
        """Cross-region SISTER (qty=1500, RM band); RM band is not auto-approve.

        Larger SISTER transfers (≥ 1000) use the RM band (auto_approve=False).
        Both RMs and NM receive outbox notifications for cross-region visibility,
        but the blocking approver is RM.
        """
        decision = await resolve_approval(
            _threshold_db("RM", 2, auto=False), TENANT_ID, "SISTER", Decimal("1500")
        )

        assert decision.required_role == "RM"
        assert decision.required_authority_level == 2
        assert decision.is_auto_approved is False
        assert decision.next_status == "PENDING_APPROVAL"

    async def test_sister_rwh_cross_region(self) -> None:
        """RM(src) and RM(dst) confirm cross-region RWH SISTER; RM band is auto-approve.

        When the RM band is configured with auto_approve=True, the transfer is
        auto-approved (no additional blocking approver required).
        NM receives an outbox notification for national visibility.
        """
        decision = await resolve_approval(
            _threshold_db("RM", 2, auto=True), TENANT_ID, "SISTER", Decimal("1500")
        )

        assert decision.required_role == "RM"
        assert decision.required_authority_level == 2
        assert decision.is_auto_approved is True
        assert decision.next_status == "APPROVED"

        # RM (2) has higher authority than WM (4) and lower than NM (1)
        assert ROLE_AUTHORITY_LEVEL["RM"] < ROLE_AUTHORITY_LEVEL["WM"]  # 2 < 4
        assert ROLE_AUTHORITY_LEVEL["NM"] < ROLE_AUTHORITY_LEVEL["RM"]  # 1 < 2

    async def test_sister_rejected_by_destination(self) -> None:
        """Destination WM declines at PENDING_DEST_CONFIRM → REJECTED (terminal).

        The destination manager's refusal terminates the transfer.  REJECTED is a
        terminal state — no further transitions are permitted from it.
        """
        # Destination WM declines
        validate_transition("SISTER", "PENDING_DEST_CONFIRM", "REJECTED")

        # REJECTED is terminal — no state change possible after rejection
        for next_state in (
            "PENDING_APPROVAL",
            "APPROVED",
            "ISSUED",
            "IN_TRANSIT",
            "RECEIVED",
            "COMPLETED",
            "DRAFT",
        ):
            with pytest.raises(InvalidStateTransitionError, match=r"SISTER.*REJECTED"):
                validate_transition("SISTER", "REJECTED", next_state)

    # ── Damage / write-off routing ────────────────────────────────────────────

    async def test_damage_within_wm_limit_auto_approved(self) -> None:
        """ADJUSTMENT qty=50 (WM band, < 100) → WM band with auto_approve=True.

        Minor damage or count variances in the WM band are configured auto-approve.
        The adjustment state machine proceeds directly to POSTED.

        Note (CLAUDE.md §24 Business Rule #13): audit_log is written for ALL
        adjustments including auto-approved ones.
        """
        decision = await resolve_approval(
            _threshold_db("WM", 4, auto=True), TENANT_ID, "ADJUSTMENT", Decimal("50")
        )

        assert decision.required_role == "WM"
        assert decision.required_authority_level == 4
        assert decision.is_auto_approved is True
        assert decision.next_status == "APPROVED"

        # ADJUSTMENT state machine: DRAFT → PENDING_APPROVAL → APPROVED → POSTED
        validate_transition("ADJUSTMENT", "DRAFT", "PENDING_APPROVAL")
        validate_transition("ADJUSTMENT", "PENDING_APPROVAL", "APPROVED")
        validate_transition("ADJUSTMENT", "APPROVED", "POSTED")

        # POSTED is terminal — no transit states exist for adjustments
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("ADJUSTMENT", "POSTED", "COMPLETED")

    async def test_damage_exceeds_wm_limit_routes_to_rm(self) -> None:
        """ADJUSTMENT qty=500 (RM band, 100–999) → RM band; auto_approve=False.

        Adjustments at or above 100 units fall into the RM band (auto_approve=False).
        RM must review before the adjustment is posted to the ledger.
        """
        decision = await resolve_approval(
            _threshold_db("RM", 2, auto=False), TENANT_ID, "ADJUSTMENT", Decimal("500")
        )

        assert decision.required_role == "RM"
        assert decision.required_authority_level == 2
        assert decision.is_auto_approved is False
        assert decision.next_status == "PENDING_APPROVAL"

    async def test_damage_exceeds_limit_final_ta(self) -> None:
        """ADJUSTMENT qty=1200 (TA band, ≥ 1000) → TA (CEO-equivalent) required.

        Large write-offs at or above 1000 units use the TA band (auto_approve=False).
        TA/SA have the same authority level (1) as NM; TA is the correct approver role
        for the highest adjustment band.
        """
        decision = await resolve_approval(
            _threshold_db("TA", 1, auto=False), TENANT_ID, "ADJUSTMENT", Decimal("1200")
        )

        assert decision.required_role == "TA"
        assert decision.required_authority_level == 1
        assert decision.is_auto_approved is False
        assert decision.next_status == "PENDING_APPROVAL"

        # TA and NM share authority level 1 — both are highest tenant-scoped authority
        assert ROLE_AUTHORITY_LEVEL["TA"] == ROLE_AUTHORITY_LEVEL["NM"] == 1

    async def test_mwh_damage_exceeds_limit_to_ta(self) -> None:
        """LM initiates large MWH damage write-off (qty=1500); TA band required.

        LM (authority_level=3) manages the Main Warehouse.  The TA band
        (authority_level=1) requires a higher authority approver.
        The multi-step escalation (LM → NM advisory → TA final) is captured
        through approval_order in the rule table; this test verifies the highest
        required approver (TA band) is returned.
        """
        decision = await resolve_approval(
            _threshold_db("TA", 1, auto=False), TENANT_ID, "ADJUSTMENT", Decimal("1500")
        )

        assert decision.required_role == "TA"
        assert decision.required_authority_level == 1
        assert decision.is_auto_approved is False
        assert decision.next_status == "PENDING_APPROVAL"

        # Authority hierarchy: LM (3) > NM (1) > TA (1) — lower number = higher authority
        assert ROLE_AUTHORITY_LEVEL["LM"] > ROLE_AUTHORITY_LEVEL["NM"]
        assert ROLE_AUTHORITY_LEVEL["NM"] == ROLE_AUTHORITY_LEVEL["TA"]  # both at 1

    # ── Missing rule guard ────────────────────────────────────────────────────

    async def test_get_required_approver_falls_back_to_org_type_default(self) -> None:
        """When no DB rule matches, resolve_approval falls back to the hardcoded
        org-type defaults (_ORG_TYPE_DEFAULTS) instead of raising.

        PULL qty=500 is in the WM band (0–999) of the default rules.
        Level 3 fallback never raises for valid tx types (PROMPT C §fallback).
        """
        decision = await resolve_approval(_mock_db_no_rule(), TENANT_ID, "PULL", Decimal("500"))
        assert decision.required_role == "WM"
        assert decision.required_authority_level == 4

    async def test_org_type_default_raises_for_unknown_tx_type(self) -> None:
        """ValueError is raised when the transaction_type is unrecognised —
        the org-type defaults only cover PULL, PUSH, ADJUSTMENT, SISTER, RECEIVE, ISSUE."""
        with pytest.raises(ValueError, match="No default approval rule"):
            await resolve_approval(_mock_db_no_rule(), TENANT_ID, "UNKNOWN_TYPE", Decimal("500"))

    # ── resolve_approval() 3-step resolution tests ───────────────────────────

    async def test_resolve_approval_product_min_wins(self) -> None:
        """When product authority floor (level 2 = RM) is tighter than the qty band
        (level 4 = WM), required_authority_level = min(2, 4) = 2.

        product_min=2 overrides threshold_level=4 because lower = higher authority.
        is_auto_approved must be False (product override disables auto-approve).
        """
        PRODUCT = "pppppppp-0000-0000-0000-000000000001"
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=(2,))),  # pam → min_level=2
                MagicMock(
                    fetchone=MagicMock(return_value=("WM", 4, True, []))
                ),  # band → WM level 4
            ]
        )

        decision = await resolve_approval(db, TENANT_ID, "PULL", Decimal("50"), product_id=PRODUCT)

        assert decision.required_authority_level == 2, (
            "product_min=2 must win over threshold=4: min(2,4)=2"
        )
        assert decision.is_auto_approved is False, (
            "auto_approve must be False when product override is in effect"
        )

    async def test_resolve_approval_qty_threshold_wins(self) -> None:
        """Without a product override, the quantity-band threshold (level 2 = RM)
        determines required_authority_level directly."""
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
        PRODUCT = "pppppppp-0000-0000-0000-000000000002"
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=(1,))),  # pam → min_level=1
                MagicMock(
                    fetchone=MagicMock(return_value=("RM", 2, False, []))
                ),  # band → RM level 2
            ]
        )

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
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("WM", 4, False, [])))
        )

        await resolve_approval(db, TENANT_ID, "SISTER", Decimal("100"))

        # Verify that the threshold query used 'PULL' not 'SISTER'
        assert db.execute.await_count == 1, "no product_id → exactly one DB call"
        call_params = db.execute.call_args_list[0].args[1]
        assert call_params["tx_type"] == "PULL", "SISTER must look up PULL bands, not SISTER bands"

    # ── Regression tests (PROMPT 3 — approval UI + routing) ──────────────────

    async def test_wm_cannot_approve_above_threshold(self) -> None:
        """Regression: WM initiator cannot auto-approve when qty falls in RM band.

        Authority level scale: WM=4, RM=2, NM/TA=1.  Lower = higher authority.
        can_approve = (caller_level <= required_level), so WM(4) cannot approve
        a band that requires RM(2).  resolve_approval must return is_auto_approved=False.

        Protects against regressions where caller_level was compared with the wrong
        direction (e.g. >=) causing WM to self-approve above-threshold transfers.
        """
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
        PRODUCT = "pppppppp-0000-0000-0000-000000000099"
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=(2,))),  # pam → min_level=2
                MagicMock(
                    fetchone=MagicMock(return_value=("WM", 4, True, []))
                ),  # band → WM, auto=True
            ]
        )

        decision = await resolve_approval(db, TENANT_ID, "PULL", Decimal("50"), product_id=PRODUCT)

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

    async def test_resolve_approval_used_not_legacy(self) -> None:
        """Gap 3 invariant: ApprovalService and route_approval() have been removed.

        All approval routing uses the module-level resolve_approval() function.
        This test fails if the legacy class is re-introduced by accident.
        """
        import services.approval_service as svc_module

        assert not hasattr(svc_module, "ApprovalService"), (
            "ApprovalService class must be absent — use resolve_approval() instead. "
            "See Gap 3 in docs/APPROVAL_WORKFLOW_REPORT.md."
        )
        assert not hasattr(svc_module, "ROLE_LEVEL"), (
            "ROLE_LEVEL (old SA=10 privilege scale) must be removed with ApprovalService. "
            "Use ROLE_AUTHORITY_LEVEL (lower = higher authority) instead."
        )
        assert hasattr(svc_module, "resolve_approval"), (
            "resolve_approval() must exist as the single approval routing entry point."
        )
        assert hasattr(svc_module, "ROLE_AUTHORITY_LEVEL"), (
            "ROLE_AUTHORITY_LEVEL must remain — it is used by inventory_service.py."
        )

    # ── Gap 4 — custom mode routing tests ────────────────────────────────────

    async def test_custom_mode_uses_per_type_rules(self) -> None:
        """In custom mode (simple_mode=False), each tx type queries its own
        approval_rule rows.  A PUSH-specific rule is used directly rather than
        falling back to PULL rules."""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("NM", 1, False, [])))
        )

        decision = await resolve_approval(db, TENANT_ID, "PUSH", Decimal("500"), simple_mode=False)

        assert decision.required_role == "NM"
        assert decision.required_authority_level == 1
        assert decision.is_auto_approved is False

        # The DB query must use "PUSH" not "PULL" in custom mode
        assert db.execute.await_count == 1, "custom PUSH rule found — no PULL fallback needed"
        call_params = db.execute.call_args_list[0].args[1]
        assert call_params["tx_type"] == "PUSH", (
            "custom mode must query the PUSH-specific rule first"
        )

    async def test_custom_mode_falls_back_to_simple(self) -> None:
        """In custom mode (simple_mode=False), when no PUSH-specific rule exists,
        fall back to PULL rules before using org-type defaults."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),  # PUSH → no rule
                MagicMock(fetchone=MagicMock(return_value=("RM", 2, False, []))),  # PULL → RM
            ]
        )

        decision = await resolve_approval(db, TENANT_ID, "PUSH", Decimal("500"), simple_mode=False)

        assert decision.required_role == "RM"
        assert decision.required_authority_level == 2
        assert db.execute.await_count == 2, (
            "two DB calls expected: PUSH lookup (None) then PULL fallback"
        )
        push_params = db.execute.call_args_list[0].args[1]
        pull_params = db.execute.call_args_list[1].args[1]
        assert push_params["tx_type"] == "PUSH"
        assert pull_params["tx_type"] == "PULL", (
            "custom mode fallback must query PULL rules when PUSH rule is absent"
        )

    async def test_sister_always_uses_pull_rules(self) -> None:
        """SISTER always queries PULL bands regardless of simple_mode.

        In custom mode, the PULL-fallback is skipped for SISTER because the
        type is remapped to PULL before any fallback check — so SISTER makes
        exactly one DB call (the PULL lookup) even in custom mode.
        """
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("WM", 4, True, [])))
        )

        await resolve_approval(db, TENANT_ID, "SISTER", Decimal("100"), simple_mode=False)

        assert db.execute.await_count == 1, (
            "SISTER makes exactly one DB call in custom mode (PULL lookup, no fallback)"
        )
        call_params = db.execute.call_args_list[0].args[1]
        assert call_params["tx_type"] == "PULL", (
            "SISTER must query PULL bands in custom mode — it is remapped before fallback"
        )
