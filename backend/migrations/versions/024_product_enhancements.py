"""product enhancements: brands, type_codes, uoms, packaging_types; new columns on products

Adds four lookup tables per tenant (all with RLS):
  product_brands, product_type_codes, product_uoms, product_packaging_types

Adds columns to products:
  short_name, description, brand_id, type_code_id, packaging_type_id

Seeds role_permissions for all new lookup endpoints (including backfills for
product:list_categories, product:create_category, product:read_next_sku from
earlier sessions that were missing from migrations).

Revision ID: 024
Revises: 022
Create Date: 2026-05-28

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "024"
down_revision = "022"
branch_labels = None
depends_on = None

# ── role permission seeds ─────────────────────────────────────────────────────
# list_*: TA, NM, RM, WM (everyone who works with the product form)
# create_*: TA, NM, RM (managers who own the product catalogue)
_LIST_ROLES   = ("SA", "TA", "NM", "RM", "WM")
_CREATE_ROLES = ("SA", "TA", "NM", "RM")

_NEW_ACTION_ROLES: list[tuple[str, str]] = []
for _action in (
    "product:list_categories",
    "product:list_brands",
    "product:list_type_codes",
    "product:list_uoms",
    "product:list_packaging_types",
    "product:read_next_sku",
):
    for _role in _LIST_ROLES:
        _NEW_ACTION_ROLES.append((_role, _action))

for _action in (
    "product:create_category",
    "product:create_brand",
    "product:create_type_code",
    "product:create_uom",
    "product:create_packaging_type",
):
    for _role in _CREATE_ROLES:
        _NEW_ACTION_ROLES.append((_role, _action))


def upgrade() -> None:
    # ── product_brands ────────────────────────────────────────────────────
    op.create_table(
        "product_brands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_brands_tenant", "product_brands", ["tenant_id"])
    op.create_unique_constraint("uq_brands_tenant_name", "product_brands", ["tenant_id", "name"])
    op.execute("ALTER TABLE product_brands ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_brands "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── product_type_codes ────────────────────────────────────────────────
    op.create_table(
        "product_type_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("description", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_type_codes_tenant", "product_type_codes", ["tenant_id"])
    op.create_unique_constraint(
        "uq_type_codes_tenant_code", "product_type_codes", ["tenant_id", "code"]
    )
    op.execute("ALTER TABLE product_type_codes ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_type_codes "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── product_uoms ──────────────────────────────────────────────────────
    op.create_table(
        "product_uoms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_uoms_tenant", "product_uoms", ["tenant_id"])
    op.create_unique_constraint("uq_uoms_tenant_name", "product_uoms", ["tenant_id", "name"])
    op.execute("ALTER TABLE product_uoms ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_uoms "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── product_packaging_types ───────────────────────────────────────────
    op.create_table(
        "product_packaging_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("units_per_package", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_pkg_types_tenant", "product_packaging_types", ["tenant_id"])
    op.create_unique_constraint(
        "uq_pkg_types_tenant_name", "product_packaging_types", ["tenant_id", "name"]
    )
    op.execute("ALTER TABLE product_packaging_types ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_packaging_types "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── products: new columns ─────────────────────────────────────────────
    op.add_column("products", sa.Column("short_name", sa.String(50), nullable=True))
    op.add_column("products", sa.Column("description", sa.Text, nullable=True))
    op.add_column(
        "products",
        sa.Column("brand_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("product_brands.id"), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("type_code_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("product_type_codes.id"), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("packaging_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("product_packaging_types.id"), nullable=True),
    )

    # ── role_permissions: seed all new lookup permissions ─────────────────
    for role_code, action_id in _NEW_ACTION_ROLES:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type)
            VALUES ('{role_code}', '{action_id}', 'FULL')
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    # Remove role permission seeds
    for role_code, action_id in _NEW_ACTION_ROLES:
        op.execute(
            f"""
            DELETE FROM role_permissions
            WHERE role_code = '{role_code}' AND action_id = '{action_id}'
            """
        )

    # Drop FK columns from products first, then the referenced tables
    op.drop_column("products", "packaging_type_id")
    op.drop_column("products", "type_code_id")
    op.drop_column("products", "brand_id")
    op.drop_column("products", "description")
    op.drop_column("products", "short_name")

    op.drop_table("product_packaging_types")
    op.drop_table("product_uoms")
    op.drop_table("product_type_codes")
    op.drop_table("product_brands")
