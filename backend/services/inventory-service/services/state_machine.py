from __future__ import annotations


class InvalidStateTransitionError(Exception):
    """Raised for any invalid state machine transition → maps to HTTP 422."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


# ── PULL — WH requests stock from RWH or MWH ────────────────────────────────
# Has a mandatory PENDING_REVIEW step before approval.
PULL_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT":              ["PENDING_REVIEW", "CANCELLED"],
    "PENDING_REVIEW":     ["PENDING_APPROVAL", "REJECTED", "CANCELLED"],
    "PENDING_APPROVAL":   ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":           ["ISSUED", "CANCELLED"],
    "ISSUED":             ["IN_TRANSIT"],
    "IN_TRANSIT":         ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED": ["RECEIVED"],
    "RECEIVED":           ["COMPLETED"],
    "COMPLETED":          [],
    "REJECTED":           [],
    "CANCELLED":          [],
}

# ── PUSH — MWH/RWH proactively sends stock down ──────────────────────────────
# No review step; ADVISED state lets the destination flag issues before dispatch.
PUSH_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT":              ["PENDING_APPROVAL", "CANCELLED"],
    "PENDING_APPROVAL":   ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":           ["ADVISED", "ISSUED", "CANCELLED"],
    "ADVISED":            ["ISSUED", "CANCELLED"],
    "ISSUED":             ["IN_TRANSIT"],
    "IN_TRANSIT":         ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED": ["RECEIVED"],
    "RECEIVED":           ["COMPLETED"],
    "COMPLETED":          [],
    "CANCELLED":          [],
}

# ── SISTER — WH ↔ WH same level ─────────────────────────────────────────────
# Both managers must explicitly confirm before any approval flows upward.
SISTER_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT":                  ["PENDING_SOURCE_CONFIRM", "CANCELLED"],
    "PENDING_SOURCE_CONFIRM": ["PENDING_DEST_CONFIRM", "CANCELLED"],
    "PENDING_DEST_CONFIRM":   ["PENDING_APPROVAL", "REJECTED"],
    "PENDING_APPROVAL":       ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":               ["ISSUED"],
    "ISSUED":                 ["IN_TRANSIT"],
    "IN_TRANSIT":             ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED":     ["RECEIVED"],
    "RECEIVED":               ["COMPLETED"],
    "COMPLETED":              [],
    "REJECTED":               [],
    "CANCELLED":              [],
}

# ── ADJUSTMENT — DAMAGE / EXCESS write-offs ──────────────────────────────────
# No transit states; terminal state is POSTED (ledger entry applied).
ADJUSTMENT_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT":            ["PENDING_APPROVAL", "CANCELLED"],
    "PENDING_APPROVAL": ["APPROVED", "REJECTED"],
    "APPROVED":         ["POSTED"],
    "POSTED":           [],
    "REJECTED":         [],
    "CANCELLED":        [],
}

_MACHINES: dict[str, dict[str, list[str]]] = {
    "PULL":       PULL_TRANSITIONS,
    "PUSH":       PUSH_TRANSITIONS,
    "SISTER":     SISTER_TRANSITIONS,
    "ADJUSTMENT": ADJUSTMENT_TRANSITIONS,
}


def get_machine(transfer_type: str) -> dict[str, list[str]]:
    """Return the state machine dict for the given transfer/adjustment type."""
    if transfer_type not in _MACHINES:
        raise ValueError(f"Unknown transfer type: {transfer_type!r}")
    return _MACHINES[transfer_type]


def validate_transition(
    transfer_type: str,
    current_status: str,
    next_status: str,
) -> None:
    """Raise InvalidStateTransitionError (→ HTTP 422) for any invalid transition."""
    machine = get_machine(transfer_type)
    allowed = machine.get(current_status, [])
    if next_status not in allowed:
        raise InvalidStateTransitionError(
            f"{transfer_type}: {current_status!r} → {next_status!r} is not permitted. "
            f"Allowed from {current_status!r}: {allowed}"
        )
