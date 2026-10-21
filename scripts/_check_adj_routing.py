"""Helper: directly invoke check_adjustment_self_approval() for a given tenant.

Usage: python scripts/_check_adj_routing.py <tenant_id> <qty1> [<qty2> ...]
Prints a JSON list of {qty, can_self_approve, approver_role, info} for role=WM, level_number=3.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://smart_user:smart_local_pass@localhost:5432/smart_dev",
)
os.environ.setdefault("DATABASE_READ_URL", os.environ["DATABASE_URL"])

_INV_SVC = os.path.join(
    os.path.dirname(__file__), "..", "backend", "services", "inventory-service"
)
sys.path.insert(0, os.path.abspath(_INV_SVC))

from shared.db.session import AsyncSessionLocal  # noqa: E402
from shared.db.rls import set_rls_context  # noqa: E402
from services.self_approval_service import check_adjustment_self_approval  # noqa: E402


class _FakeUser:
    def __init__(self, role: str, level_number: int) -> None:
        self.role = role
        self.level_number = level_number


async def main() -> None:
    tenant_id = sys.argv[1]
    qtys = [Decimal(x) for x in sys.argv[2:]]
    user = _FakeUser("WM", 3)

    out = []
    async with AsyncSessionLocal() as session:
        await set_rls_context(
            session, tenant_id, "00000000-0000-0000-0000-000000000000"
        )
        for qty in qtys:
            can_self, approver_role, info = await check_adjustment_self_approval(
                session, tenant_id, user, "DAMAGE", qty, qty
            )
            out.append(
                {
                    "qty": str(qty),
                    "can_self_approve": can_self,
                    "approver_role": approver_role,
                    "info": info,
                }
            )

    print(json.dumps(out))


if __name__ == "__main__":
    asyncio.run(main())
