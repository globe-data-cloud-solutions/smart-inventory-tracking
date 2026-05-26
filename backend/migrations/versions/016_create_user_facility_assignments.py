"""Create user_facility_assignments table — PRIMARY / ACTING / DELEGATE facility access.

Three assignment types:
  PRIMARY  — exactly 1 per user, permanent, created at onboarding.
  ACTING   — time-bounded, multiple allowed, created by any manager in scope.
  DELEGATE — time-bounded, permission-scoped, created by any manager in scope.

JWT warehouse_id always equals the user's PRIMARY facility.
ABAC unions PRIMARY + all currently-active ACTING / DELEGATE assignments.

Revision ID: 016
Revises: 015
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_facility_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organization_node.id"), nullable=False),
        # VARCHAR CHECK — assignment types are a small closed set, not a separate table
        sa.Column("assignment_type", sa.String(20), nullable=False),
        sa.Column("role_code", sa.String(10), nullable=False),
        sa.Column("valid_from", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "assignment_type IN ('PRIMARY','ACTING','DELEGATE')",
            name="chk_assignment_type",
        ),
    )
    op.create_index("idx_ufa_tenant_user", "user_facility_assignments",
                    ["tenant_id", "user_id"])
    op.create_index("idx_ufa_tenant_facility", "user_facility_assignments",
                    ["tenant_id", "facility_id"])
    # Partial index: enforce at most one active PRIMARY per user per tenant
    op.create_index(
        "idx_ufa_unique_primary",
        "user_facility_assignments",
        ["tenant_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("assignment_type = 'PRIMARY' AND is_active = true"),
    )
    op.execute("ALTER TABLE user_facility_assignments ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON user_facility_assignments "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_facility_assignments")
    op.drop_index("idx_ufa_unique_primary", table_name="user_facility_assignments")
    op.drop_index("idx_ufa_tenant_facility", table_name="user_facility_assignments")
    op.drop_index("idx_ufa_tenant_user", table_name="user_facility_assignments")
    op.drop_table("user_facility_assignments")
