"""remove hardcoded pack_size check constraint from products table

Allows any positive integer pack_size instead of only 1/4/6/12.
The Pydantic schema now enforces pack_size >= 1 at the API layer.

Revision ID: 022
Revises: 021
Create Date: 2026-05-28

"""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_products_pack_size", "products", type_="check")


def downgrade() -> None:
    op.create_check_constraint(
        "ck_products_pack_size",
        "products",
        "pack_size = ANY (ARRAY[1, 4, 6, 12])",
    )
