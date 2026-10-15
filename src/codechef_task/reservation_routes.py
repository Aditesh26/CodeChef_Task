"""HTTP endpoints for the temporary reservation lifecycle."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from codechef_task.config import settings
from codechef_task.database import get_db_session
from codechef_task.models import (
    Booking,
    BookingStatus,
    Event,
    EventStatus,
    Reservation,
    ReservationStatus,
    Seat,
)

router = APIRouter()


class ReservationCreate(BaseModel):
    seat_id: int = Field(gt=0)


class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    seat_id: int
    status: ReservationStatus
    created_at: datetime
    expires_at: datetime


def _as_utc(value: datetime) -> datetime:
    """Interpret MariaDB DATETIME values as UTC and normalize aware values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _reservation_response(reservation: Reservation) -> ReservationRead:
    return ReservationRead(
        id=reservation.id,
        event_id=reservation.event_id,
        seat_id=reservation.seat_id,
        status=reservation.status,
        created_at=_as_utc(reservation.created_at),
        expires_at=_as_utc(reservation.expires_at),
    )


async def _expire_if_elapsed(
    session: AsyncSession, reservation: Reservation, now: datetime
) -> bool:
    """Persist expiration and free the generated active-seat key when due."""
    if (
        reservation.status == ReservationStatus.ACTIVE.value
        and _as_utc(reservation.expires_at) <= now
    ):
        reservation.status = ReservationStatus.EXPIRED.value
        reservation.updated_at = now
        await session.flush()
        return True
    return False


async def _read_reservation_location(
    session: AsyncSession, reservation_id: int
) -> tuple[int, int]:
    """Find immutable seat coordinates before starting the lifecycle transaction."""
    location = (
        await session.execute(
            select(Reservation.event_id, Reservation.seat_id).where(
                Reservation.id == reservation_id
            )
        )
    ).one_or_none()
    if location is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    # End the lookup transaction so a later InnoDB locking read does not use a
    # repeatable-read snapshot created before it waited for the seat row.
    await session.commit()
    return location


async def _lock_reservation_and_seat(
    session: AsyncSession,
    reservation_id: int,
    event_id: int,
    seat_id: int,
) -> Reservation:
    """Lock the seat then reservation, consistently across lifecycle writes."""
    seat = await session.scalar(
        select(Seat)
        .where(Seat.event_id == event_id, Seat.id == seat_id)
        .with_for_update()
    )
    if seat is None:
        raise HTTPException(status_code=404, detail="Reservation not found")

    reservation = await session.scalar(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .with_for_update()
    )
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return reservation


@router.post(
    "/api/events/{event_id}/reservations",
    response_model=ReservationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_reservation(
    payload: ReservationCreate,
    event_id: int = Path(gt=0),
    session: AsyncSession = Depends(get_db_session),
) -> ReservationRead:
    """Temporarily hold an available seat, serializing attempts on its seat row."""
    response: ReservationRead | None = None
    conflict: str | None = None
    try:
        async with session.begin():
            # This existing InnoDB row is the mutex for this event/seat. Every
            # reservation lifecycle operation locks it before touching a hold.
            seat = await session.scalar(
                select(Seat)
                .where(Seat.event_id == event_id, Seat.id == payload.seat_id)
                .with_for_update()
            )
            if seat is None:
                event_exists = await session.scalar(
                    select(Event.id).where(Event.id == event_id)
                )
                if event_exists is None:
                    raise HTTPException(status_code=404, detail="Event not found")
                raise HTTPException(status_code=404, detail="Seat not found for this event")

            # This is the first consistent read in the transaction, after any
            # wait for the seat lock, so it observes state committed by the
            # request that held the lock before us.
            event = await session.scalar(select(Event).where(Event.id == event_id))
            if event is None:
                raise HTTPException(status_code=404, detail="Event not found")
            if event.status != EventStatus.OPEN.value:
                raise HTTPException(status_code=409, detail="Event is not open for reservations")

            now = datetime.now(UTC)
            active_reservation = await session.scalar(
                select(Reservation)
                .where(
                    Reservation.event_id == event_id,
                    Reservation.active_seat_id == seat.id,
                )
            )
            if active_reservation is not None:
                await _expire_if_elapsed(session, active_reservation, now)
                if active_reservation.status == ReservationStatus.ACTIVE.value:
                    conflict = "Seat is held by an active reservation"

            if conflict is None:
                confirmed_booking_id = await session.scalar(
                    select(Booking.id)
                    .where(
                        Booking.event_id == event_id,
                        Booking.seat_id == seat.id,
                        Booking.status == BookingStatus.CONFIRMED.value,
                    )
                    .limit(1)
                )
                if confirmed_booking_id is not None:
                    conflict = "Seat already has a confirmed booking"

            if conflict is None:
                reservation = Reservation(
                    event_id=event_id,
                    seat_id=seat.id,
                    status=ReservationStatus.ACTIVE.value,
                    created_at=now,
                    updated_at=now,
                    expires_at=now + timedelta(seconds=settings.reservation_hold_seconds),
                )
                session.add(reservation)
                await session.flush()
                await session.refresh(reservation)
                response = _reservation_response(reservation)
    except IntegrityError:
        # The context manager has rolled back before this handler is reached.
        raise HTTPException(status_code=409, detail="Seat is no longer available") from None

    # Commit any lazy expiration before reporting a later availability conflict.
    if conflict is not None:
        raise HTTPException(status_code=409, detail=conflict)
    assert response is not None
    return response


@router.get(
    "/api/reservations/{reservation_id}", response_model=ReservationRead
)
async def get_reservation(
    reservation_id: int = Path(gt=0),
    session: AsyncSession = Depends(get_db_session),
) -> ReservationRead:
    """Return current status and persist expiration when the hold has elapsed."""
    event_id, seat_id = await _read_reservation_location(session, reservation_id)
    async with session.begin():
        reservation = await _lock_reservation_and_seat(
            session, reservation_id, event_id, seat_id
        )
        await _expire_if_elapsed(session, reservation, datetime.now(UTC))
        return _reservation_response(reservation)


@router.delete(
    "/api/reservations/{reservation_id}", response_model=ReservationRead
)
async def cancel_reservation(
    reservation_id: int = Path(gt=0),
    session: AsyncSession = Depends(get_db_session),
) -> ReservationRead:
    """Cancel a current hold; terminal reservation states cannot be reactivated."""
    event_id, seat_id = await _read_reservation_location(session, reservation_id)
    response: ReservationRead | None = None
    conflict: str | None = None
    async with session.begin():
        reservation = await _lock_reservation_and_seat(
            session, reservation_id, event_id, seat_id
        )
        now = datetime.now(UTC)
        expired = await _expire_if_elapsed(session, reservation, now)
        if expired:
            conflict = "Reservation has expired"
        elif reservation.status != ReservationStatus.ACTIVE.value:
            conflict = "Only an active reservation can be cancelled"
        else:
            reservation.status = ReservationStatus.CANCELLED.value
            reservation.updated_at = now
            await session.flush()
            response = _reservation_response(reservation)

    if conflict is not None:
        raise HTTPException(status_code=409, detail=conflict)
    assert response is not None
    return response
