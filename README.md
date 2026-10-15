# The Last Seat

An asynchronous FastAPI backend and initial database schema for the college
recruitment task.

## Prerequisites and setup

- Python 3.14 or newer
- [`uv`](https://docs.astral.sh/uv/)
- MariaDB listening on the configured host and port

From the repository root, install runtime and development dependencies:

```powershell
uv sync
```

Set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` in `.env`.
The defaults for the host and port target local MariaDB at `127.0.0.1:3307`;
the database named by `DB_NAME` must already exist. `.env` is ignored by Git.
Set `RESERVATION_HOLD_SECONDS` to a positive number to change the temporary
hold duration; the default is 300 seconds (5 minutes).

## Run the API

```powershell
uv run uvicorn codechef_task.app:app --reload
```

The API is available at `http://127.0.0.1:8000`. `/health` checks the API
process, and `/health/db` runs a simple database query.

## Initial schema and demo inventory

The schema has five tables:

- `events` stores an event's slug, status, schedule, ticket price, and currency.
- `seats` stores numbered seats for an event. A unique constraint on
  `(event_id, seat_number)` prevents duplicate seat numbers within one event.
- `reservations` stores temporary seat holds, their expiry timestamp, and an
  explicit status: `active`, `converted`, `expired`, or `cancelled`.
- `bookings` stores confirmed or cancelled booking records and the amount paid.
- `payments` stores individual payment attempts separately from bookings, with
  their own amount, provider reference, and status.

Amounts use fixed precision `NUMERIC(10, 2)`, not floating point. Timestamps
are stored as timezone-aware SQLAlchemy datetimes; use UTC when writing times.
Foreign keys ensure each reservation and booking refers to a seat in the same
event.

MariaDB enforces the confirmed-seat rule with the generated `confirmed_seat_id`
column on `bookings` and the unique index on `(event_id, confirmed_seat_id)`.
The generated column contains the seat ID only while a booking is confirmed;
otherwise it is `NULL`. MariaDB permits multiple `NULL` values in a unique
index, while rejecting a second confirmed row for the same event and seat.
An equivalent generated column and index enforce at most one active reservation
for a seat. An active reservation is transitioned to `expired` by reservation
requests once its expiry time is reached.

Initialize missing tables and seed the demo event with seats 1 through 500:

```powershell
uv run python -m codechef_task.seed
```

The initializer uses SQLAlchemy `create_all()`, which creates missing tables
and does not drop or recreate existing tables or the database. Running the
seed command again fills in missing seat numbers without duplicating existing
ones. If the event already has seats outside 1–500, the seed command stops
instead of deleting them. `create_all()` is suitable for this initial schema;
use a migration tool before evolving a deployed schema.

## Reservation API

Create a hold for a seat in an open event:

```http
POST /api/events/1/reservations
Content-Type: application/json

{"seat_id": 42}
```

The response is `201 Created` and includes the reservation identifier and UTC
timestamps:

```json
{
  "id": 17,
  "event_id": 1,
  "seat_id": 42,
  "status": "active",
  "created_at": "2026-10-16T12:00:00Z",
  "expires_at": "2026-10-16T12:05:00Z"
}
```

Retrieve a reservation with `GET /api/reservations/17`; cancel an active one
with `DELETE /api/reservations/17`. Both return the same reservation shape.
Unknown events or seats return `404`. Closed/cancelled events, already-held or
booked seats, and attempts to cancel a terminal reservation return `409`.

The lifecycle is `active` to one of `cancelled`, `expired`, or (in a future
booking flow) `converted`. Terminal states are never changed back to active.
Expiration is lazy: create requests check the seat's active hold, and retrieve
requests refresh that reservation's status. If `expires_at <=` the current UTC
time, they persist `expired`; a past timestamp by itself does not release the
seat. No worker is required, but an expired hold on an untouched seat remains
stored as active until a request processes it.

### Concurrency behavior

Create, retrieve, and cancel operations lock the concrete seat row with
`SELECT ... FOR UPDATE` before changing its hold. Two create requests for the
same seat therefore serialize on the same InnoDB row; the second request sees
the first committed active hold and receives `409`. The existing unique index
on `(event_id, active_seat_id)` remains a database-level backstop if another
writer bypasses this code. Expiration changes the reservation status and flushes
that change before a new hold is inserted, clearing the generated active-seat
key in the same transaction. Confirmed bookings are checked independently and
remain protected by the unique confirmed-booking index.

The MariaDB integration test exercises simultaneous requests for the same
seat and for different seats. SQLite tests cover the lifecycle and response
rules, but SQLite does not validate InnoDB row-lock semantics. This milestone
does not include authentication or reservation ownership checks, booking
creation, an expiration worker, or load testing; it makes no 10,000-user
capacity claim. Event status changes and any future booking-creation flow must
also coordinate with the seat-lock protocol.

## Run tests

```powershell
uv run pytest
```
