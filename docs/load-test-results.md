# Basic concurrent load test

## How to reproduce

Use the configured MariaDB database and apply the schema plus checkout
migration first. Start one local Uvicorn worker in a terminal:

```powershell
uv run --locked uvicorn codechef_task.app:app --host 127.0.0.1 --port 8000
```

Run the test from another terminal:

```powershell
uv run --locked python scripts/load_test.py --base-url http://127.0.0.1:8000 --requests 100 --seats 10 --checkout-retries 3 --concurrency 50
```

The script creates an open event with a random `load-test-<uuid>` slug and the
requested number of seats. It sends reservation requests round-robin across
that limited inventory, then sends the requested number of simultaneous
checkout calls for each successful reservation. The first checkout succeeds;
the concurrent retries should return the stored response. It queries active
holds before checkout and checks both active-hold and confirmed-booking
uniqueness after all requests finish.

By default, cleanup deletes only the newly created event by its primary key.
InnoDB cascading foreign keys remove its test seats, reservations, bookings,
and payments. The script never selects, updates, or deletes the demo event or
other event IDs. `--keep-data` opts out of cleanup for inspection. If the
process is forcibly terminated before cleanup, its printed unique slug can be
used to identify the leftover isolated event; verify the slug before removing
anything manually.

Options can be changed to repeat the run at another inventory, request count,
retry count, or client concurrency limit. The script exits nonzero if expected
status counts or database invariants do not match. The readiness probe is not
included in the reported load request counts.

## Measured run

Run date: 2026-10-16. One measured run was made on Windows with Python 3.14.1,
one local Uvicorn worker, and MariaDB 13.0.2 using InnoDB on port 3307. The
script used 50 concurrent client request slots, 10 seats, and a local HTTP
connection to `127.0.0.1:8765`. Other machine specifications and competing
system load were not captured. Response time includes time waiting for one of
the configured client request slots.

| Phase                       | Requests | 2xx successes | Expected 409 rejections | Unexpected errors | Duration |   Throughput |       p50 |       p95 |       p99 |
| --------------------------- | -------: | ------------: | ----------------------: | ----------------: | -------: | -----------: | --------: | --------: | --------: |
| Reservation contention      |      100 |            10 |                      90 |                 0 |  0.322 s | 311.01 req/s | 229.88 ms | 297.96 ms | 301.24 ms |
| Concurrent checkout retries |       30 |            30 |                       0 |                 0 |  0.189 s | 158.59 req/s | 141.31 ms | 171.17 ms | 175.52 ms |
| Combined request phases     |      130 |            40 |                      90 |                 0 |  0.511 s | 254.55 req/s | 183.30 ms | 294.14 ms | 301.03 ms |

The reservation phase returned 10 HTTP 201 responses and 90 HTTP 409
responses. Checkout returned 10 HTTP 201 responses and 20 HTTP 200 idempotent
replays. There were no other response codes, network errors, or timeouts.

Database checks passed after reservation contention: 10 active reservations
and zero duplicate active seats. Before cleanup, the event had 10 seats, 10
reservations, zero active reservations, 10 bookings (all confirmed), and 10
payments. Both duplicate-active-seat and duplicate-confirmed-seat queries
returned zero rows. The script reported successful cleanup of the test event
and its cascading rows, then checked that no rows remained for the test event.

## What this does and does not demonstrate

This is a small local smoke/load test of HTTP routes plus MariaDB row locking;
it is not a production capacity or endurance benchmark. It covers one
reservation contention burst and concurrent idempotent checkout retries for
the winners. It does not test multiple API workers, remote network latency,
connection-pool saturation at high volume, long-duration traffic, client
think-time, or 10,000 concurrent users. Results are a single run and vary with
hardware, server load, database configuration, and connection-pool settings.
