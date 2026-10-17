# Functional audit

Audit date: 2026-10-16. This table reflects the implementation after the
availability, history, delayed settlement, and confirmed-booking cancellation
work in this milestone.

| Requirement | Status | Relevant endpoint, code, constraint, and tests | Remaining limitation |
|---|---|---|---|
| View available seats, reserve seats, and confirm bookings | **Implemented** | `GET /api/events/{event_id}/seats` in `src/codechef_task/inventory_routes.py:list_event_seats` reports `available`, `reserved`, or `booked`. Reservation creation is `POST /api/events/{event_id}/reservations`; checkout is `POST /api/reservations/{reservation_id}/checkout`. `tests/test_inventory_routes.py:test_seat_status_booking_history_and_confirmed_booking_cancellation` covers state before/after hold, expiry, cancellation, booking, and reallocation. | Availability is a point-in-time view and may change immediately; reservation creation remains the authoritative operation and may return 409. |
| Prevent multiple users from successfully booking the same seat | **Implemented** | Seat-first `SELECT ... FOR UPDATE` on lifecycle writes; unique `uq_bookings_confirmed_event_seat` on `(event_id, confirmed_seat_id)` and `uq_reservations_active_event_seat`. Tests: `tests/test_schema.py:test_unique_index_allows_only_one_confirmed_booking_per_event_seat`, `tests/test_reservation_mariadb.py:test_concurrent_reservations_are_safe_on_mariadb`. | Safety depends on InnoDB and writers respecting the same locking/constraint protocol. This is not a measured capacity guarantee. |
| Implement temporary reservations that automatically expire | **Partially implemented** | `Reservation.expires_at`, `ReservationStatus`, and `reservation_routes.py:_expire_if_elapsed`; the seat listing also processes elapsed holds using the same seat-first lock. Tests: `tests/test_reservation_routes.py:test_reservation_endpoints_and_expiration_with_sqlite`, `tests/test_inventory_routes.py:test_seat_status_booking_history_and_confirmed_booking_cancellation`, and delayed expiry in `tests/test_delayed_payment.py:test_delayed_payment_success_failure_expiry_cancel_and_replay`. | Expiry is lazy, not a background worker. An untouched hold can remain stored as `active` after its deadline until an API operation processes it. |
| Support booking cancellations and seat reallocation | **Implemented** | Temporary hold cancellation: `DELETE /api/reservations/{reservation_id}`. Confirmed booking cancellation: `POST /api/bookings/{booking_id}/cancel` in `inventory_routes.py:cancel_confirmed_booking`; it locks the seat and changes the booking to `cancelled`, clearing generated `confirmed_seat_id` while preserving history. The inventory/history test confirms seat reuse and idempotent repeated cancellation. | Cancellation does not issue a refund; the succeeded payment stays in history. |
| Simulate payment success, failure, and delayed transactions | **Implemented** | Checkout accepts `success`, `failure`, or `delayed`; `POST /api/payments/{payment_id}/settle` resolves pending attempts. Delayed success/failure, expiration/cancellation before settlement, and rollback are tested in `tests/test_delayed_payment.py`. Concurrent settlement retries are tested in the MariaDB integration test. | Delayed settlement is a later explicit API request, not an automatic timer or provider callback. This is simulation only and makes no real charge. |
| Maintain consistency when requests are repeated or concurrent | **Implemented** | Checkout/settlement/cancellation use database transactions and the seat-first lock order. Unique `Booking.reservation_id`, `Payment.booking_id`, and the confirmed-seat index enforce database-level uniqueness. Tests include checkout replay/rollback, delayed settlement rollback, and concurrent MariaDB reservation/checkout/settlement attempts. | Idempotency is scoped to a reservation/payment ID, not a general client-supplied idempotency key. |
| Provide APIs for booking history and reservation status | **Implemented** | `GET /api/events/{event_id}/bookings` returns paginated event booking records and payment status/details; `GET /api/reservations/{reservation_id}` returns reservation status. `tests/test_inventory_routes.py` checks booking/payment history; existing reservation tests cover status retrieval. | History is event-wide and not associated with an authenticated owner. Authentication and user-specific booking history are not implemented. |

## Payment and expiry states

Delayed checkout creates a `pending` booking and `pending` payment while the
reservation remains `active`. Successful settlement changes them to a
`confirmed` booking, `succeeded` payment, and `converted` reservation. Failed
settlement changes the booking to `cancelled`, payment to `failed`, and
reservation to `cancelled`. If the hold is cancelled or lazily expires first,
the pending payment is failed and the booking is cancelled; later settlement
cannot confirm it.

There is no background expiry or payment-settlement worker. A pending delayed
payment remains pending until settlement is requested or an API operation
cancels/expires its reservation.
