"""094 — tenant isolation for transfer_order_lines and inventory_transaction_keys.

RB-1 follow-up to 091. Two tables carried tenant data with no RLS policy, so the
non-owner runtime role could read and write them across tenants:

  transfer_order_lines
      Has tenant_id. Gets ENABLE ROW LEVEL SECURITY and the standard
      tenant_isolation policy (same expression as 091/093).

  inventory_transaction_keys
      Had no tenant_id. The idempotency key was the global primary key, so two
      tenants using the same key collided (409 DUPLICATE_TRANSACTION for the
      second tenant) and the key lookup could see other tenants' keys. Gets:
        - tenant_id uuid, backfilled from the transaction it registers
          (inventory_transactions.id). A key whose transaction no longer exists
          was never committed (key and transaction share one DB transaction), so
          it is dropped rather than assigned to a tenant.
        - primary key (tenant_id, idempotency_key)
        - ENABLE ROW LEVEL SECURITY and the tenant_isolation policy

FORCE stays off (D8), as on every other table. outbox and tenants are left as
they are: outbox is global by design, and tenants is the tenant record itself.

Downgrade removes the RLS and the tenant_id column and restores the
single-column primary key. It fails with a unique violation if two tenants
registered the same key while 094 was in force, which is deliberate: that data
cannot be restored without choosing one tenant's key to keep.
"""

from alembic import op

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None


# Same expression as 091 (tenant_isolation) and 093 (partition policy).
V_EXPR = (
    "(tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid "
    "OR COALESCE(current_setting('app.is_sa', true), '') = 'on')"
)


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} USING {V_EXPR} WITH CHECK {V_EXPR}"
    )


def _disable_tenant_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # transfer_order_lines: policy only, no schema change.
    _enable_tenant_rls("transfer_order_lines")

    # inventory_transaction_keys: drop keys with no committed transaction, then
    # assign each remaining key the tenant of its transaction.
    op.execute(
        """
        DELETE FROM inventory_transaction_keys k
        WHERE NOT EXISTS (
            SELECT 1 FROM inventory_transactions t WHERE t.id = k.transaction_id
        )
        """
    )
    op.execute("ALTER TABLE inventory_transaction_keys ADD COLUMN tenant_id uuid")
    op.execute(
        """
        UPDATE inventory_transaction_keys k
           SET tenant_id = t.tenant_id
          FROM inventory_transactions t
         WHERE t.id = k.transaction_id
        """
    )
    op.execute(
        "ALTER TABLE inventory_transaction_keys ALTER COLUMN tenant_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE inventory_transaction_keys "
        "DROP CONSTRAINT inventory_transaction_keys_pkey"
    )
    op.execute(
        "ALTER TABLE inventory_transaction_keys "
        "ADD PRIMARY KEY (tenant_id, idempotency_key)"
    )
    _enable_tenant_rls("inventory_transaction_keys")


def downgrade() -> None:
    _disable_tenant_rls("inventory_transaction_keys")
    op.execute(
        "ALTER TABLE inventory_transaction_keys "
        "DROP CONSTRAINT inventory_transaction_keys_pkey"
    )
    op.execute("ALTER TABLE inventory_transaction_keys DROP COLUMN tenant_id")
    op.execute(
        "ALTER TABLE inventory_transaction_keys ADD PRIMARY KEY (idempotency_key)"
    )
    _disable_tenant_rls("transfer_order_lines")
