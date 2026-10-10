"""078 — Tenant renewal requests.

TA-initiated renewal requests against an expiring/grace/read-only contract,
and the SA queue to triage them. One OPEN request per tenant at a time
(partial unique index). RLS policy copied verbatim from 072's tenant_addons
table (tenant-scoped, no FORCE — app role owns these rows and FORCE would
block SA cross-tenant reads, CLAUDE.md §7).

Revision ID: 078
Revises:     077
Create Date: 2026-10-09
"""
from __future__ import annotations

from alembic import op

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_renewal_requests (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL REFERENCES tenants(id),
            requested_by        UUID NOT NULL,
            requested_by_email  VARCHAR(255),
            message             TEXT,
            status              VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                                CHECK (status IN ('OPEN', 'HANDLED', 'CANCELLED')),
            handled_by          UUID,
            handled_note        TEXT,
            handled_at          TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_tenant_renewal_requests_tenant "
        "ON tenant_renewal_requests (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_renewal_requests_one_open "
        "ON tenant_renewal_requests (tenant_id) WHERE status = 'OPEN'"
    )
    op.execute("ALTER TABLE tenant_renewal_requests ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_renewal_requests "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_renewal_requests")
