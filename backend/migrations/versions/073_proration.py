"""073 — invoice_kind on payments, for S11 mid-period proration.

Replaces "plan change = no proration" (CLAUDE.md §15 S5) for ANNUAL upgrades
and PURCHASED add-ons. A PRORATION invoice is a second payments row raised
automatically, in the SAME DB transaction as the plan change / add-on grant,
alongside (never instead of) the tenant's normal recurring PERIOD invoices.

payments.invoice_kind distinguishes the two: 'PERIOD' (today's existing rows
— the default, backfilled onto every row that already exists) and
'PRORATION' (new in S11). Paying or cancelling a PRORATION invoice never
moves the subscription's period or the tenant's contract — see
shared/billing/proration.py and payments.mark_paid()'s invoice_kind branch.

Recon (2026-10-07): the "one PENDING invoice per subscription" rule
(create_invoice's INVOICE_ALREADY_PENDING check) is CODE-ONLY — there is no
unique index on payments enforcing it (confirmed: `\\d payments` has no such
constraint). This migration therefore adds only the column; the scoping of
that rule to invoice_kind='PERIOD' (so a pending PRORATION invoice never
blocks a normal renewal/period invoice, and vice versa — rule 6) is a code
change in create_invoice(), not a schema change.

Revision ID: 073
Revises:     072
Create Date: 2026-10-07
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def _refuse_if_proration_invoices_exist() -> None:
    """payments is never deleted (CLAUDE.md §15) and a PRORATION row is real
    billing history the moment it is raised — downgrade cannot drop the
    column a PRORATION row depends on to be distinguished from a normal
    PERIOD invoice. Raises instead of silently reclassifying history."""
    bind = op.get_bind()
    count = bind.execute(
        text("SELECT count(*) FROM payments WHERE invoice_kind = 'PRORATION'")
    ).scalar()
    if count:
        raise RuntimeError(
            f"073 downgrade blocked: {count} PRORATION invoices exist; "
            "payments is never deleted"
        )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payments ADD COLUMN invoice_kind VARCHAR(12) NOT NULL DEFAULT 'PERIOD' "
        "CHECK (invoice_kind IN ('PERIOD', 'PRORATION'))"
    )


def downgrade() -> None:
    _refuse_if_proration_invoices_exist()
    op.execute("ALTER TABLE payments DROP COLUMN IF EXISTS invoice_kind")
