"""Create monthly partitions for inventory_transactions.
Run at infrastructure setup and monthly via Celery beat / cron.
Usage: python scripts/create_partitions.py --months 3

Runs as the runtime role, which cannot CREATE or ALTER tables: each month goes
through the SECURITY DEFINER ensure_inventory_partition(date) (migration 092),
which creates the partition if missing and (re)applies RLS + tenant_isolation.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def partition_name(year: int, month: int) -> str:
    return f"inventory_transactions_{year}_{month:02d}"


async def create_partitions(months_ahead: int) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)

    today = date.today()
    async with Session() as session:
        for i in range(months_ahead):
            target = today + relativedelta(months=i)
            name = partition_name(target.year, target.month)

            await session.execute(
                text("SELECT ensure_inventory_partition(:m)"),
                {"m": date(target.year, target.month, 1)},
            )
            print(f"  Ensured partition: {name}")

        await session.commit()
        print(f"Done. Ensured {months_ahead} partition(s).")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--months", type=int, default=3, help="Number of months to create ahead"
    )
    args = parser.parse_args()
    asyncio.run(create_partitions(args.months))
