# The Last Seat

The Last Seat is an asynchronous FastAPI backend for a college recruitment
task. It demonstrates a seat inventory, temporary reservations, and an atomic
booking plus simulated-payment flow using MariaDB and SQLAlchemy 2.x.

## Architecture

- `src/codechef_task/app.py` creates the FastAPI application and health routes.
- `reservation_routes.py` handles holds, reservation retrieval, and cancellation.
- `inventory_routes.py` lists seat availability, event booking history, and
  confirmed-booking cancellation.
- `checkout_routes.py` converts one valid reservation into a booking and
  simulated payment, including delayed settlement.
- `models.py` defines Event, Seat, Reservation, Booking, and Payment.
- `database.py` configures the async SQLAlchemy engine/session using `asyncmy`.
- `schema.py`, `migrate.py`, and `seed.py` initialize tables, add checkout
  uniqueness constraints, and seed demo inventory respectively.
- Mermaid diagrams: [ERD](docs/ERD.md) and
  [reservation/booking workflow](docs/Booking-Workflow.md).
- Requirement-by-requirement review: [functional audit](docs/functional-audit.md).

MariaDB/InnoDB is the concurrency authority. SQLite is used for fast isolated
route and constraint tests; it does not reproduce InnoDB row locking.

## Prerequisites

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)
- MariaDB 13.x for local development, or Docker Desktop with Docker Compose

## Local setup with uv

Install the locked dependencies:

```powershell
uv sync --locked
```

Create the local environment file from the placeholder template and edit its
database credentials. PowerShell:

```powershell
Copy-Item .env.example .env
```

For a host-installed MariaDB, `.env` uses `127.0.0.1:3307`. Create the database
and a least-privilege local user in a MariaDB client, replacing the example
password before executing:

```sql
CREATE DATABASE the_last_seat;
CREATE USER 'lastseat'@'localhost' IDENTIFIED BY 'replace-with-a-local-password';
GRANT ALL PRIVILEGES ON the_last_seat.* TO 'lastseat'@'localhost';
```

If the database or user already exists, preserve it and adjust the grants as
needed; do not drop or recreate an existing database. The application reads
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and
`RESERVATION_HOLD_SECONDS` from environment variables or `.env`. `.env` is
ignored by Git and excluded from Docker builds. Never put real credentials in
`.env.example`.

Initialize missing tables and apply the safe, forward-only checkout migration:

```powershell
uv run --locked python -m codechef_task.migrate
```

The migration adds unique keys on `bookings.reservation_id` and
`payments.booking_id`, and updates the booking status check to allow `pending`
delayed bookings. It checks for duplicates before adding keys; it changes no
booking rows and never drops tables or data. Existing confirmed/cancelled rows
remain valid. SQLAlchemy `create_all()` creates missing tables but does not
evolve existing ones; this small migration is for the current milestone. Use a
versioned migration tool for subsequent schema evolution.

Seed or complete the demo event inventory:

```powershell
uv run --locked python -m codechef_task.seed
```

The seed operation is repeatable and creates exactly seat numbers 1–500 for
`the-last-seat-demo` if that event has no out-of-range seats. It does not
duplicate existing seats or delete data.

## Run the API

```powershell
uv run --locked uvicorn codechef_task.app:app --reload
```

The API listens at `http://127.0.0.1:8000`. Interactive API docs are at
`/docs`.

## API endpoints

### `GET /health`

Checks that the API process responds:

```http
GET /health
```

```json
{"status":"healthy"}
```

### `GET /health/db`

Runs `SELECT 1`. On success:

```json
{"status":"healthy","database":"available"}
```

Request: `GET /health/db`. When the database is unavailable, it returns HTTP
503 with this generic response:

```json
{"detail":{"status":"unhealthy","database":"unavailable"}}
```

Credentials and internal exception details are not returned.

### `POST /api/events/{event_id}/reservations`

Creates a temporary hold for an available seat in an open event:

```http
POST /api/events/1/reservations
Content-Type: application/json

{"seat_id":42}
```

HTTP 201 response:

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

Unknown event/seat returns 404. Closed events or unavailable seats return 409.

### `GET /api/events/{event_id}/seats`

Lists seats in number order. Example request: `GET /api/events/1/seats`.
Example response:

```json
{
  "event_id": 1,
  "seats": [
    {"seat_id": 12, "seat_number": 1, "status": "available"},
    {"seat_id": 13, "seat_number": 2, "status": "reserved"},
    {"seat_id": 14, "seat_number": 3, "status": "booked"}
  ]
}
```

Statuses are `available`, `reserved`, or `booked`. The listing processes
elapsed active holds with the same locking and lazy-expiry behavior used by
reservation operations. It is a point-in-time view; a subsequent reservation
request can still lose a race and return 409. Unknown event returns 404.

### `GET /api/reservations/{reservation_id}`

Example request: `GET /api/reservations/17`. Returns HTTP 200 and the
reservation shape shown in the creation example, lazily persisting `expired`
when the hold deadline has passed. Unknown reservation returns 404.

### `DELETE /api/reservations/{reservation_id}`

Example request: `DELETE /api/reservations/17`. Cancels an active hold and
returns HTTP 200 with the updated reservation shape shown above (with `status`
set to `cancelled`). A terminal or expired hold returns 409. Cancellation does
not delete reservation history.

### `POST /api/reservations/{reservation_id}/checkout`

Simulates checkout for an active, unexpired reservation. The request chooses
only a simulated outcome; price and currency are loaded from the event:

```http
POST /api/reservations/17/checkout
Content-Type: application/json

{"outcome":"success"}
```

Immediate outcomes are `success` and `failure`. Example HTTP 201 response for
success:

```json
{
  "booking_id": 21,
  "reservation_id": 17,
  "booking_status": "confirmed",
  "payment_id": 33,
  "payment_status": "succeeded",
  "amount": "25.00",
  "currency": "USD"
}
```

For an asynchronous simulated response, send `{"outcome":"delayed"}`. Checkout
creates a `pending` booking and payment and leaves the reservation active. It
returns HTTP 201 in the same response shape, with both statuses set to
`pending`. Later, explicitly settle it:

```http
POST /api/payments/33/settle
Content-Type: application/json

{"outcome":"success"}
```

The settlement response is HTTP 200 with final booking/payment statuses. Use
`failure` to release the seat instead. Settlement is an explicit later
request, not a timer or background worker. If the reservation is cancelled or
expires first, its pending payment is changed to failed and its booking to
cancelled; it cannot later confirm. Repeated checkout or settlement returns
the stored result even if the retry supplies a different outcome. Expired or
cancelled reservations without an existing checkout return 409; unknown IDs
return 404. Database write errors return a generic 409.

### `GET /api/events/{event_id}/bookings`

Returns event booking history, newest first, including cancelled and pending
records and optional payment details. Example request:
`GET /api/events/1/bookings?limit=100&offset=0`.

```json
{
  "event_id": 1,
  "items": [{
    "id": 21,
    "event_id": 1,
    "seat_id": 14,
    "reservation_id": 17,
    "status": "confirmed",
    "amount_paid": "25.00",
    "currency": "USD",
    "created_at": "2026-10-16T12:00:00Z",
    "payment": {
      "id": 33,
      "status": "succeeded",
      "amount": "25.00",
      "currency": "USD",
      "created_at": "2026-10-16T12:00:00Z"
    }
  }]
}
```

`limit` is 1–500 (default 100); `offset` defaults to 0. Unknown event returns
404. This is event-wide history; no authentication or user ownership filtering
exists.

### `POST /api/bookings/{booking_id}/cancel`

Cancels a confirmed booking while preserving its row. Example:
`POST /api/bookings/21/cancel`. The response is the booking-history item above
with `status: "cancelled"`; the seat becomes available for a new reservation.
Repeated cancellation returns the same record. The succeeded payment remains
in history: cancellation does not issue a refund. Only confirmed bookings can
be cancelled through this endpoint.

## Schema, lifecycle, and concurrency

The five models are shown in [docs/ERD.md](docs/ERD.md); the state and lock
flow is shown in [docs/Booking-Workflow.md](docs/Booking-Workflow.md). Money
uses `NUMERIC(10, 2)`. Times use UTC. Composite seat foreign keys ensure a
reservation or booking points to a seat belonging to the same event.

Reservation states are `active`, `converted`, `expired`, and `cancelled`.
Checkout success changes `active → converted`; failure changes `active →
cancelled`. Failed payment keeps a cancelled booking and failed payment as
history while releasing inventory. Terminal reservations are not reactivated.
Booking states are `pending`, `confirmed`, and `cancelled`. A delayed checkout
persists pending booking/payment records while retaining its active hold. The
explicit settlement endpoint either confirms/converts/succeeds or
cancels/cancels/fails. Expiry or hold cancellation first also fails a pending
attempt.

Expiry is lazy: an API operation processes an elapsed hold; there is no expiry
worker. Until a request touches an expired hold, its stored status can remain
`active`, but reservation/checkout paths compare `expires_at` before proceeding.

Every reservation and checkout mutation locks the concrete seat row with
`SELECT ... FOR UPDATE`, then locks the reservation. The lock serializes
writers for that seat in InnoDB. Checkout writes booking, payment, and
reservation state inside one transaction, so an error rolls back all of them.
Database unique constraints back up application checks:

- `(event_id, active_seat_id)` permits at most one active reservation per seat.
- `(event_id, confirmed_seat_id)` permits at most one confirmed booking per
  seat. The generated seat key is NULL for pending and cancelled historical
  rows; pending inventory remains protected by its active reservation.
- Unique `bookings.reservation_id` permits one booking per reservation.
- Unique `payments.booking_id` permits one payment row per booking.
- `(event_id, seat_number)` prevents repeated seat numbers within an event.

The checkout idempotency scope is the reservation: the first outcome persists,
and repeated or concurrent requests return the stored payment and booking.
There is one attempt per reservation; a failed payment is terminal and a retry
requires a new reservation. A delayed outcome is resolved by an explicit later
settlement request; it does not sleep in a request or create an untracked task.
This is a deterministic simulator, not payment provider integration, and it
does not create an external charge.

The MariaDB integration test exercises same-seat reservation, duplicate
checkout, and delayed-settlement concurrency. SQLite tests validate API and transaction behavior but
cannot establish InnoDB locking behavior. Locks coordinate only code paths
that follow the same seat-first protocol. There is no authentication or
reservation ownership check, so this API is not ready for public use. Event
administration, refunds, provider retries, and background expiry are not
implemented. A small reproducible load smoke test is documented in
[docs/load-test-results.md](docs/load-test-results.md); it is not a capacity
benchmark. No claim of 10,000 concurrent users is made. Scaling beyond a single
app/database setup would require representative load tests, database pool
tuning, and likely horizontally scaled API workers; shared database
constraints and row locks remain necessary across workers.

## Docker Compose

Docker Compose starts the API and MariaDB. The database has a persistent named
volume. The API connects to the service name `db` on container port 3306. Its
host-published port defaults to 3308 to avoid colliding with the existing local
MariaDB on 3307.

```powershell
Copy-Item .env.example .env
# Edit .env and replace all placeholder credentials.
docker compose up --build -d
docker compose ps
```

Initialize schema and apply the checkout migration, then seed the demo event:

```powershell
docker compose exec api python -m codechef_task.migrate
docker compose exec api python -m codechef_task.seed
```

Check `http://127.0.0.1:8000/health` and `/health/db`. The database can be
reached from the host on `127.0.0.1:3308` by default; containers use `db:3306`.
To stop the services while preserving the named database volume:

```powershell
docker compose down
```

Do not use `docker compose down -v` if you need to keep the container database.
The MariaDB image initializes credentials/database only for a new empty data
volume; changing `.env` later does not rewrite existing database users.

## Tests

Run the entire suite:

```powershell
uv run --locked --cache-dir .uv-cache pytest -q -p no:cacheprovider
```

SQLite-based tests need no MariaDB. The MariaDB concurrency test uses the
configured database when available and skips if the service cannot be reached.

## Basic load test

Start the API in one terminal, then run the repeatable contention test in
another:

```powershell
uv run --locked uvicorn codechef_task.app:app --host 127.0.0.1 --port 8000
uv run --locked python scripts/load_test.py --requests 100 --seats 10 --checkout-retries 3 --concurrency 50
```

The script requires the configured MariaDB and initialized schema. Each run
creates a uniquely named open event and its own small seat inventory, competes
reservation requests for those seats, then makes concurrent retries for each
successful checkout. It queries database invariants before deleting only that
run's event; event cascades remove its test rows. `--keep-data` retains the
isolated event for inspection. Results and limitations from the measured run
are recorded in [docs/load-test-results.md](docs/load-test-results.md).
