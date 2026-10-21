"""076 — Password reset tokens (B2).

Schema only. No endpoints are added in this migration.

password_reset_tokens — platform-level, mirrors email_verification_tokens
(071): looked up by token from a public endpoint before login, so no
tenant_id / no RLS; only auth-service touches it.

Revision ID: 076
Revises:     075
Create Date: 2026-10-08
"""

from __future__ import annotations

from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE password_reset_tokens (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id),
            token_hash  TEXT NOT NULL UNIQUE,
            expires_at  TIMESTAMPTZ NOT NULL,
            used_at     TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_password_reset_tokens_user ON password_reset_tokens (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS password_reset_tokens")
