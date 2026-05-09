from __future__ import annotations


class InvalidStateTransitionError(Exception):
    """HTTP 422 — raised for any invalid state machine transition."""

    def __init__(self, current: str, attempted: str) -> None:
        super().__init__(f"Cannot transition from {current!r} to {attempted!r}")
        self.current = current
        self.attempted = attempted


TRANSFER_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT":      ["SUBMITTED", "CANCELLED"],
    "SUBMITTED":  ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":   ["IN_TRANSIT", "CANCELLED"],
    "IN_TRANSIT": ["RECEIVED", "CANCELLED"],
    "RECEIVED":   ["CLOSED"],
    "CLOSED":     [],
    "REJECTED":   [],
    "CANCELLED":  [],
}

ADJUSTMENT_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT":     ["SUBMITTED", "CANCELLED"],
    "SUBMITTED": ["APPROVED", "REJECTED"],
    "APPROVED":  ["APPLIED"],
    "APPLIED":   [],
    "REJECTED":  [],
    "CANCELLED": [],
}


def validate_transition(
    machine: dict[str, list[str]],
    current: str,
    next_state: str,
) -> None:
    """Raises InvalidStateTransitionError → HTTP 422 for any invalid transition."""
    if next_state not in machine.get(current, []):
        raise InvalidStateTransitionError(current=current, attempted=next_state)
