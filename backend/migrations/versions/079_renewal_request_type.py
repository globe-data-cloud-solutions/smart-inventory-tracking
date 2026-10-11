"""079 — request_type on tenant_renewal_requests (RENEWAL | UPGRADE).

Adds request_type + requested_tier so the same renewal-request queue also
carries TA-initiated upgrade requests. One OPEN request per (tenant, type)
at a time (partial unique index, replacing the 078 one-open-per-tenant
index). SA still handles the request; the plan change itself goes through
the existing tier-change path (S13), not this table.

Revision ID: 079
Revises:     078
Create Date: 2026-10-11
"""
from __future__ import annotations

from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_renewal_requests "
        "ADD COLUMN request_type VARCHAR(20) NOT NULL DEFAULT 'RENEWAL' "
        "CHECK (request_type IN ('RENEWAL', 'UPGRADE'))"
    )
    op.execute(
        "ALTER TABLE tenant_renewal_requests "
        "ADD COLUMN requested_tier VARCHAR(20) NULL "
        "CHECK (requested_tier IS NULL OR requested_tier IN ('STARTER', 'GROWTH', 'ENTERPRISE'))"
    )
    op.execute(
        "ALTER TABLE tenant_renewal_requests "
        "ADD CONSTRAINT ck_tenant_renewal_requests_upgrade_tier "
        "CHECK ((request_type = 'UPGRADE') = (requested_tier IS NOT NULL))"
    )
    op.execute("DROP INDEX uq_tenant_renewal_requests_one_open")
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_renewal_requests_one_open_per_type "
        "ON tenant_renewal_requests (tenant_id, request_type) WHERE status = 'OPEN'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE tenant_renewal_requests "
        "SET status = 'CANCELLED', handled_note = 'auto-cancelled by downgrade 079' "
        "WHERE request_type = 'UPGRADE' AND status = 'OPEN'"
    )
    op.execute("DROP INDEX uq_tenant_renewal_requests_one_open_per_type")
    op.execute(
        "ALTER TABLE tenant_renewal_requests "
        "DROP CONSTRAINT ck_tenant_renewal_requests_upgrade_tier"
    )
    op.execute("ALTER TABLE tenant_renewal_requests DROP COLUMN requested_tier")
    op.execute("ALTER TABLE tenant_renewal_requests DROP COLUMN request_type")
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_renewal_requests_one_open "
        "ON tenant_renewal_requests (tenant_id) WHERE status = 'OPEN'"
    )
