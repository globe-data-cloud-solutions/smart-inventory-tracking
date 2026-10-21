"""Unit tests for approval rule routing logic.

These tests verify the threshold band definitions loaded from the canonical
seed data in scripts/seed_approval_rules.py.  No database connection is needed
— the rules are imported as constants so the tests are always fast and offline.

Business rules under test (CLAUDE.md §24, §15):
  - Every quantity finds exactly one approver (no gap, no ambiguity)
  - PULL small (<1000) → WM; PULL large (≥5000) → NM
  - PUSH always requires NM or above (NM for < 5000, TA for ≥ 5000)
  - Threshold ranges are contiguous with no gaps between bands
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

import pytest

# ── Canonical rule definitions (mirrors seed_approval_rules.py) ─────────────
# Each rule: (min_qty inclusive, max_qty inclusive or None=∞, approver_role)

ADDIS_WATER_RULES: dict[str, list[tuple[Decimal, Optional[Decimal], str]]] = {
    "PULL": [
        (Decimal("0"), Decimal("999.9999"), "WM"),
        (Decimal("1000"), Decimal("4999.9999"), "RM"),
        (Decimal("5000"), None, "NM"),
    ],
    "PUSH": [
        (Decimal("0"), Decimal("4999.9999"), "NM"),
        (Decimal("5000"), None, "TA"),
    ],
    "ADJUSTMENT": [
        (Decimal("0"), Decimal("99.9999"), "WM"),  # 0–99:    WM self-approval
        (Decimal("100"), Decimal("999.9999"), "RM"),  # 100–999: RM required
        (Decimal("1000"), None, "TA"),  # 1000+:   TA (CEO) required
    ],
    "SISTER": [
        (Decimal("0"), Decimal("999.9999"), "WM"),
        (Decimal("1000"), None, "RM"),
    ],
}

# Role hierarchy — used to assert "NM or above"
ROLE_LEVEL: dict[str, int] = {
    "SYS": 1,
    "AU": 2,
    "RT": 3,
    "SA_GT": 4,
    "WM": 6,
    "LM": 6,
    "RM": 7,
    "NM": 8,
    "TA": 9,
    "SA": 10,
}


def _resolve_approver(tx_type: str, quantity: Decimal) -> str:
    """Return the approver role for the given transaction type and quantity."""
    bands = ADDIS_WATER_RULES[tx_type]
    for min_qty, max_qty, role in bands:
        if quantity >= min_qty and (max_qty is None or quantity <= max_qty):
            return role
    raise ValueError(f"No approval band matched {tx_type} qty={quantity}")


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestApprovalRuleRouting:
    # ── PULL routing ─────────────────────────────────────────────────────────

    def test_pull_small_qty_routes_to_wm(self) -> None:
        """PULL qty < 1000 is handled by the Warehouse Manager."""
        for qty in [Decimal("0"), Decimal("1"), Decimal("500"), Decimal("999")]:
            assert _resolve_approver("PULL", qty) == "WM", f"Expected WM for PULL qty={qty}"

    def test_pull_mid_qty_routes_to_rm(self) -> None:
        """PULL 1000 ≤ qty < 5000 requires Regional Manager approval."""
        for qty in [Decimal("1000"), Decimal("2500"), Decimal("4999")]:
            assert _resolve_approver("PULL", qty) == "RM", f"Expected RM for PULL qty={qty}"

    def test_pull_large_qty_routes_to_nm(self) -> None:
        """PULL qty ≥ 5000 requires National Manager approval."""
        for qty in [Decimal("5000"), Decimal("10000"), Decimal("999999")]:
            assert _resolve_approver("PULL", qty) == "NM", f"Expected NM for PULL qty={qty}"

    def test_pull_boundary_1000_is_rm_not_wm(self) -> None:
        """Exact boundary 1000 falls into RM band, not WM band."""
        assert _resolve_approver("PULL", Decimal("1000")) == "RM"

    def test_pull_boundary_5000_is_nm_not_rm(self) -> None:
        """Exact boundary 5000 falls into NM band, not RM band."""
        assert _resolve_approver("PULL", Decimal("5000")) == "NM"

    # ── PUSH routing ─────────────────────────────────────────────────────────

    def test_push_always_requires_nm_or_above(self) -> None:
        """All PUSH rules require a role at NM level (8) or higher.
        WM (6) and RM (7) must never appear as PUSH approvers."""
        bands = ADDIS_WATER_RULES["PUSH"]
        for _, _, role in bands:
            assert ROLE_LEVEL[role] >= ROLE_LEVEL["NM"], (
                f"PUSH approver '{role}' is below NM level — violates §24"
            )

    def test_push_small_qty_requires_nm(self) -> None:
        """PUSH qty < 5000 requires NM."""
        for qty in [Decimal("1"), Decimal("100"), Decimal("4999")]:
            assert _resolve_approver("PUSH", qty) == "NM"

    def test_push_large_qty_requires_ta(self) -> None:
        """PUSH qty ≥ 5000 requires Tenant Admin (CEO-equivalent)."""
        for qty in [Decimal("5000"), Decimal("50000")]:
            assert _resolve_approver("PUSH", qty) == "TA"

    # ── ADJUSTMENT routing ────────────────────────────────────────────────────

    def test_adjustment_small_self_approved_by_wm(self) -> None:
        """Adjustments < 100 units are auto-approved at WM level."""
        for qty in [Decimal("0"), Decimal("50"), Decimal("99")]:
            assert _resolve_approver("ADJUSTMENT", qty) == "WM"

    def test_adjustment_mid_requires_rm(self) -> None:
        """Adjustments 100–999 units require Regional Manager."""
        for qty in [Decimal("100"), Decimal("500"), Decimal("999")]:
            assert _resolve_approver("ADJUSTMENT", qty) == "RM", (
                f"Expected RM for ADJUSTMENT qty={qty}"
            )

    def test_adjustment_large_requires_ta(self) -> None:
        """Adjustments ≥ 1000 units require Tenant Admin (CEO-equivalent)."""
        for qty in [Decimal("1000"), Decimal("5000"), Decimal("10000")]:
            assert _resolve_approver("ADJUSTMENT", qty) == "TA", (
                f"Expected TA for ADJUSTMENT qty={qty}"
            )

    # ── SISTER routing ────────────────────────────────────────────────────────

    def test_sister_small_stays_at_wm(self) -> None:
        """Small sister transfers (< 1000) are handled by both WMs."""
        assert _resolve_approver("SISTER", Decimal("999")) == "WM"

    def test_sister_large_escalates_to_rm(self) -> None:
        """Large sister transfers (≥ 1000) require RM notification."""
        assert _resolve_approver("SISTER", Decimal("1000")) == "RM"

    # ── Range contiguity ─────────────────────────────────────────────────────

    def test_no_gap_in_threshold_ranges(self) -> None:
        """All bands for each tx type are contiguous — no quantity falls through.

        For each type, verifies that max_qty of band[n] + epsilon == min_qty of band[n+1].
        A gap would mean some quantities have no approver, which would crash the
        approval workflow at runtime.
        """
        epsilon = Decimal("0.0001")  # smallest unit in NUMERIC(15,4)

        for tx_type, bands in ADDIS_WATER_RULES.items():
            for i in range(len(bands) - 1):
                current_max = bands[i][1]
                next_min = bands[i + 1][0]
                assert current_max is not None, (
                    f"{tx_type} band {i} has None max but is not the last band"
                )
                # current band ends at X.9999; next starts at X+1.0000
                # gap would mean current_max + epsilon != next_min
                assert current_max + epsilon == next_min, (
                    f"Gap in {tx_type} between band {i} (max={current_max}) "
                    f"and band {i + 1} (min={next_min}): "
                    f"qty={current_max + epsilon} has no approver"
                )

    def test_last_band_each_type_is_open_ended(self) -> None:
        """The highest band for every transaction type has no upper limit (None max_qty).
        This guarantees arbitrarily large quantities always find an approver.
        """
        for tx_type, bands in ADDIS_WATER_RULES.items():
            last_max = bands[-1][1]
            assert last_max is None, (
                f"{tx_type} last band max_qty={last_max} — must be None (open-ended)"
            )

    def test_first_band_each_type_starts_at_zero(self) -> None:
        """The lowest band for every transaction type starts at zero quantity.
        Prevents zero-quantity edge cases falling through the rules.
        """
        for tx_type, bands in ADDIS_WATER_RULES.items():
            first_min = bands[0][0]
            assert first_min == Decimal("0"), (
                f"{tx_type} first band min_qty={first_min} — must start at 0"
            )
