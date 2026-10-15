import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from codechef_task.models import Booking, Event, Reservation, Seat
from codechef_task.schema import initialize_schema
from codechef_task.seed import seed_event_inventory


def test_seed_is_idempotent_and_creates_500_distinct_seats() -> None:
    async def scenario() -> None:
        test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await initialize_schema(test_engine)
        session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

        async with session_factory() as session:
            event = await seed_event_inventory(session)
            event_id = event.id
            await session.commit()

        async with session_factory() as session:
            event_again = await seed_event_inventory(session)
            await session.commit()
            assert event_again.id == event_id
            seat_numbers = list(
                await session.scalars(
                    select(Seat.seat_number)
                    .where(Seat.event_id == event_id)
                    .order_by(Seat.seat_number)
                )
            )

        assert seat_numbers == list(range(1, 501))
        assert len(set(seat_numbers)) == 500

        # Initialization is repeatable and leaves existing data intact.
        await initialize_schema(test_engine)
        await test_engine.dispose()

    asyncio.run(scenario())


def test_unique_index_allows_only_one_confirmed_booking_per_event_seat() -> None:
    async def scenario() -> None:
        test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await initialize_schema(test_engine)
        session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

        async with session_factory() as session:
            event = Event(
                slug="booking-constraint-test",
                name="Constraint Test",
                ticket_price=Decimal("10.00"),
                currency="USD",
            )
            session.add(event)
            await session.flush()
            seat = Seat(event_id=event.id, seat_number=1)
            session.add(seat)
            await session.flush()

            session.add_all(
                [
                    Booking(
                        event_id=event.id,
                        seat_id=seat.id,
                        status="cancelled",
                        amount_paid=Decimal("0.00"),
                        currency="USD",
                    ),
                    Booking(
                        event_id=event.id,
                        seat_id=seat.id,
                        status="confirmed",
                        amount_paid=Decimal("10.00"),
                        currency="USD",
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            session.add(
                Booking(
                    event_id=event.id,
                    seat_id=seat.id,
                    status="confirmed",
                    amount_paid=Decimal("10.00"),
                    currency="USD",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        await test_engine.dispose()

    asyncio.run(scenario())


def test_only_one_active_reservation_per_event_seat() -> None:
    async def scenario() -> None:
        test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await initialize_schema(test_engine)
        session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

        async with session_factory() as session:
            event = Event(
                slug="reservation-constraint-test",
                name="Constraint Test",
                ticket_price=Decimal("10.00"),
                currency="USD",
            )
            session.add(event)
            await session.flush()
            seat = Seat(event_id=event.id, seat_number=1)
            session.add(seat)
            await session.flush()
            expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
            session.add(
                Reservation(event_id=event.id, seat_id=seat.id, expires_at=expiry)
            )
            await session.commit()

        async with session_factory() as session:
            session.add(
                Reservation(event_id=event.id, seat_id=seat.id, expires_at=expiry)
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        await test_engine.dispose()

    asyncio.run(scenario())


def test_seat_numbers_are_unique_within_an_event() -> None:
    async def scenario() -> None:
        test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await initialize_schema(test_engine)
        session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

        async with session_factory() as session:
            event = Event(
                slug="seat-constraint-test",
                name="Constraint Test",
                ticket_price=Decimal("10.00"),
                currency="USD",
            )
            session.add(event)
            await session.flush()
            session.add(Seat(event_id=event.id, seat_number=1))
            await session.commit()

        async with session_factory() as session:
            session.add(Seat(event_id=event.id, seat_number=1))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        await test_engine.dispose()

    asyncio.run(scenario())
