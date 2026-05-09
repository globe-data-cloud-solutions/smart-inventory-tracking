"""Create monthly partitions for inventory_transactions.
Run at infrastructure setup and monthly via Celery beat / cron.
Usage: python scripts/create_partitions.py --months 3
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


def partition_range(year: int, month: int) -> tuple[str, str]:
    start = date(year, month, 1)
    end = start + relativedelta(months=1)
    return start.isoformat(), end.isoformat()


async def create_partitions(months_ahead: int) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)

    today = date.today()
    async with Session() as session:
        for i in range(months_ahead):
            target = today + relativedelta(months=i)
            name = partition_name(target.year, target.month)
            start, end = partition_range(target.year, target.month)

            await session.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {name} "
                    f"PARTITION OF inventory_transactions "
                    f"FOR VALUES FROM ('{start}') TO ('{end}')"
                )
            )
            print(f"  Created partition: {name} ({start} → {end})")

        await session.commit()
        print(f"Done. Created {months_ahead} partition(s).")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=3, help="Number of months to create ahead")
    args = parser.parse_args()
    asyncio.run(create_partitions(args.months))
