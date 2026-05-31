"""031 — clean slate: nullable tenant_id/cognito_sub on users, drop role+warehouse_id,
drop user_facility_assignments; new positions and personnel_positions tables.

Session 1 architectural change:
- Role is no longer a column on users — it is determined by the user's
  position (positions table) via personnel_positions.
- warehouse_id is no longer on users — facility assignment is via personnel_positions.
- tenant_id and cognito_sub become nullable so the SA platform account can
  exist outside any tenant's hierarchy without a Cognito identity.

Revision ID: 031
Revises:     030
Create Date: 2026-05-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Make tenant_id and cognito_sub nullable on users ─────────────────────
    # SA platform account has no tenant and no Cognito identity.
    # These may already be nullable if the raw SQL was run in PART A; the
    # op.alter_column calls are idempotent here.
    op.execute(
        "ALTER TABLE users ALTER COLUMN tenant_id DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE users ALTER COLUMN cognito_sub DROP NOT NULL"
    )

    # ── Drop role and warehouse_id from users ─────────────────────────────────
    # Role is now determined via positions/personnel_positions.
    # warehouse_id is now determined via personnel_positions → positions → node_id.
    op.drop_column("users", "role")
    op.drop_column("users", "warehouse_id")
    op.drop_column("users", "region_id")

    # ── Drop user_facility_assignments (replaced by personnel_positions) ──────
    op.drop_table("user_facility_assignments")

    # ── positions ─────────────────────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("role_code", sa.String(20), nullable=False),
        sa.Column("reports_to_position_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["organization_node.id"]),
        sa.ForeignKeyConstraint(["reports_to_position_id"], ["positions.id"]),
        sa.CheckConstraint(
            "role_code IN ('NM','RM','LM','WM','AU','RT')",
            name="positions_role_code_check",
        ),
        sa.UniqueConstraint("node_id", "title", name="uq_positions_node_title"),
    )
    op.create_index("idx_positions_tenant", "positions", ["tenant_id"])
    op.create_index("idx_positions_node", "positions", ["node_id", "role_code"])

    op.execute("ALTER TABLE positions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON positions "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── personnel_positions ───────────────────────────────────────────────────
    op.create_table(
        "personnel_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_type", sa.String(20), nullable=False),
        sa.Column("valid_from", sa.Date(),
                  server_default=sa.text("CURRENT_DATE"), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["position_id"], ["positions.id"]),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"]),
        sa.CheckConstraint(
            "assignment_type IN ('PRIMARY','ACTING','DELEGATE')",
            name="personnel_positions_type_check",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="personnel_positions_dates_check",
        ),
    )
    op.create_index("idx_personnel_positions_user",
                    "personnel_positions", ["tenant_id", "user_id"])
    op.create_index("idx_personnel_positions_position",
                    "personnel_positions", ["position_id", "is_active"])
    # Unique index: each user may have only ONE active PRIMARY assignment
    op.execute(
        "CREATE UNIQUE INDEX idx_one_primary_per_user "
        "ON personnel_positions (user_id) "
        "WHERE assignment_type = 'PRIMARY' AND is_active = true;"
    )

    op.execute("ALTER TABLE personnel_positions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON personnel_positions "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("personnel_positions")
    op.drop_table("positions")

    # Recreate user_facility_assignments (from migration 016)
    op.create_table(
        "user_facility_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_type", sa.String(20), nullable=False),
        sa.Column("role_code", sa.String(20), nullable=False),
        sa.Column("valid_from", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["facility_id"], ["organization_node.id"]),
    )

    # Restore columns (nullable — can't know original NOT NULL state with data present)
    op.add_column("users", sa.Column("region_id",
                  postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("warehouse_id",
                  postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(20), nullable=True))

    op.alter_column("users", "tenant_id",
                    existing_type=postgresql.UUID(as_uuid=True),
                    nullable=False)
    op.alter_column("users", "cognito_sub",
                    existing_type=sa.String(255),
                    nullable=False)
