"""Apply the small, non-destructive Milestone 4 uniqueness migration."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from codechef_task.database import engine
from codechef_task.schema import initialize_schema

_UNIQUE_KEYS = (
    ("bookings", "reservation_id", "uq_bookings_reservation_id"),
    ("payments", "booking_id", "uq_payments_booking_id"),
)


async def apply_checkout_constraints(target_engine: AsyncEngine = engine) -> None:
    """Add unique keys only when absent; refuse to hide existing duplicates."""
    async with target_engine.begin() as connection:
        for table, column, constraint in _UNIQUE_KEYS:
            index_rows = (
                await connection.execute(
                    text(
                        "SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE, SEQ_IN_INDEX "
                        "FROM information_schema.STATISTICS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table "
                        "ORDER BY INDEX_NAME, SEQ_IN_INDEX"
                    ),
                    {"table": table},
                )
            ).all()
            indexes: dict[str, list[tuple[str, int]]] = {}
            for name, indexed_column, non_unique, sequence in index_rows:
                if non_unique == 0:
                    indexes.setdefault(name, []).append((indexed_column, sequence))
            if any(
                [column_name for column_name, _ in sorted(parts, key=lambda part: part[1])]
                == [column]
                for parts in indexes.values()
            ):
                continue

            duplicates = (
                await connection.execute(
                    text(
                        f"SELECT `{column}`, COUNT(*) AS row_count FROM `{table}` "
                        f"WHERE `{column}` IS NOT NULL GROUP BY `{column}` "
                        "HAVING COUNT(*) > 1 LIMIT 1"
                    )
                )
            ).first()
            if duplicates is not None:
                raise RuntimeError(
                    f"Cannot add {constraint}: duplicate {column} values exist in {table}. "
                    "Review those rows before retrying the migration."
                )
            await connection.execute(
                text(
                    f"ALTER TABLE `{table}` ADD CONSTRAINT `{constraint}` "
                    f"UNIQUE (`{column}`)"
                )
            )


async def main() -> None:
    await initialize_schema(engine)
    await apply_checkout_constraints(engine)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
