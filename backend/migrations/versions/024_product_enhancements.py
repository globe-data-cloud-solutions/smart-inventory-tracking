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

revision = "024"
down_revision = "022"
branch_labels = None
depends_on = None

# ── role permission seeds ─────────────────────────────────────────────────────
# list_*: TA, NM, RM, WM (everyone who works with the product form)
# create_*: TA, NM, RM (managers who own the product catalogue)
_LIST_ROLES = ("SA", "TA", "NM", "RM", "WM")
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
    conn = op.get_bind()

    # ── product_brands ────────────────────────────────────────────────────
    conn.execute(
        sa.text("""
        CREATE TABLE IF NOT EXISTS product_brands (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  UUID NOT NULL,
            name       VARCHAR(100) NOT NULL,
            is_active  BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_brands_tenant ON product_brands (tenant_id)"
        )
    )
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_brands_tenant_name') THEN "
            "    ALTER TABLE product_brands ADD CONSTRAINT uq_brands_tenant_name UNIQUE (tenant_id, name); "
            "  END IF; "
            "END $$"
        )
    )
    conn.execute(sa.text("ALTER TABLE product_brands ENABLE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='product_brands' AND policyname='tenant_isolation') THEN "
            "    CREATE POLICY tenant_isolation ON product_brands "
            "    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid); "
            "  END IF; "
            "END $$"
        )
    )

    # ── product_type_codes ────────────────────────────────────────────────
    conn.execute(
        sa.text("""
        CREATE TABLE IF NOT EXISTS product_type_codes (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL,
            code        VARCHAR(10) NOT NULL,
            description VARCHAR(100),
            is_active   BOOLEAN NOT NULL DEFAULT true,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_type_codes_tenant ON product_type_codes (tenant_id)"
        )
    )
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_type_codes_tenant_code') THEN "
            "    ALTER TABLE product_type_codes ADD CONSTRAINT uq_type_codes_tenant_code UNIQUE (tenant_id, code); "
            "  END IF; "
            "END $$"
        )
    )
    conn.execute(sa.text("ALTER TABLE product_type_codes ENABLE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='product_type_codes' AND policyname='tenant_isolation') THEN "
            "    CREATE POLICY tenant_isolation ON product_type_codes "
            "    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid); "
            "  END IF; "
            "END $$"
        )
    )

    # ── product_uoms ──────────────────────────────────────────────────────
    conn.execute(
        sa.text("""
        CREATE TABLE IF NOT EXISTS product_uoms (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  UUID NOT NULL,
            name       VARCHAR(50) NOT NULL,
            is_active  BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_uoms_tenant ON product_uoms (tenant_id)"
        )
    )
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_uoms_tenant_name') THEN "
            "    ALTER TABLE product_uoms ADD CONSTRAINT uq_uoms_tenant_name UNIQUE (tenant_id, name); "
            "  END IF; "
            "END $$"
        )
    )
    conn.execute(sa.text("ALTER TABLE product_uoms ENABLE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='product_uoms' AND policyname='tenant_isolation') THEN "
            "    CREATE POLICY tenant_isolation ON product_uoms "
            "    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid); "
            "  END IF; "
            "END $$"
        )
    )

    # ── product_packaging_types ───────────────────────────────────────────
    conn.execute(
        sa.text("""
        CREATE TABLE IF NOT EXISTS product_packaging_types (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL,
            name             VARCHAR(50) NOT NULL,
            units_per_package INTEGER NOT NULL DEFAULT 1,
            is_active        BOOLEAN NOT NULL DEFAULT true,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_pkg_types_tenant ON product_packaging_types (tenant_id)"
        )
    )
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_pkg_types_tenant_name') THEN "
            "    ALTER TABLE product_packaging_types ADD CONSTRAINT uq_pkg_types_tenant_name UNIQUE (tenant_id, name); "
            "  END IF; "
            "END $$"
        )
    )
    conn.execute(
        sa.text("ALTER TABLE product_packaging_types ENABLE ROW LEVEL SECURITY")
    )
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='product_packaging_types' AND policyname='tenant_isolation') THEN "
            "    CREATE POLICY tenant_isolation ON product_packaging_types "
            "    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid); "
            "  END IF; "
            "END $$"
        )
    )

    # ── products: new columns (all guarded with IF NOT EXISTS) ────────────
    conn.execute(
        sa.text("ALTER TABLE products ADD COLUMN IF NOT EXISTS short_name VARCHAR(50)")
    )
    conn.execute(
        sa.text("ALTER TABLE products ADD COLUMN IF NOT EXISTS description TEXT")
    )
    conn.execute(
        sa.text(
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES product_brands(id)"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS type_code_id UUID REFERENCES product_type_codes(id)"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS packaging_type_id UUID REFERENCES product_packaging_types(id)"
        )
    )

    # ── role_permissions: seed all new lookup permissions ─────────────────
    for role_code, action_id in _NEW_ACTION_ROLES:
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_code, action_id, grant_type) "
                "VALUES (:rc, :aid, 'FULL') "
                "ON CONFLICT (role_code, action_id) DO NOTHING"
            ),
            {"rc": role_code, "aid": action_id},
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
