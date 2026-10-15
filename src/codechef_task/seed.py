import asyncio
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from codechef_task.database import SessionLocal, engine
from codechef_task.models import Event, EventStatus, Seat
from codechef_task.schema import initialize_schema

SEAT_COUNT = 500
DEMO_EVENT_SLUG = "the-last-seat-demo"


async def seed_event_inventory(
    session: AsyncSession,
    *,
    slug: str = DEMO_EVENT_SLUG,
    name: str = "The Last Seat Demo Event",
    seat_count: int = SEAT_COUNT,
) -> Event:
    # Ensure one event has seats numbered 1 through seat_count, without duplicates
    if seat_count < 1:
        raise ValueError("seat_count must be at least 1")

    event = await session.scalar(select(Event).where(Event.slug == slug))
    if event is None:
        event = Event(
            slug=slug,
            name=name,
            ticket_price=Decimal("25.00"),
            currency="USD",
            status=EventStatus.DRAFT.value,
        )
        session.add(event)
        await session.flush()

    existing_numbers = set(
        await session.scalars(select(Seat.seat_number).where(Seat.event_id == event.id))
    )
    expected_numbers = set(range(1, seat_count + 1))
    unexpected_numbers = existing_numbers - expected_numbers
    if unexpected_numbers:
        raise ValueError(
            "event already has seat numbers outside the requested inventory range"
        )

    missing_numbers = expected_numbers - existing_numbers
    session.add_all(
        Seat(event_id=event.id, seat_number=seat_number)
        for seat_number in sorted(missing_numbers)
    )
    await session.flush()
    return event


async def main() -> None:
    await initialize_schema(engine)
    async with SessionLocal() as session:
        event = await seed_event_inventory(session)
        seat_total = await session.scalar(
            select(func.count(Seat.id)).where(Seat.event_id == event.id)
        )
        if seat_total != SEAT_COUNT:
            raise RuntimeError(f"expected {SEAT_COUNT} seats, found {seat_total}")
        await session.commit()
        print(
            f"Seeded event {event.slug!r} with {seat_total} seats numbered 1-{SEAT_COUNT}."
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
