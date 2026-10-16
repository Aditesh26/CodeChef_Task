# Reservation and booking workflow

```mermaid
flowchart TD
    A[Client requests seat hold] --> B[Begin transaction and lock seat row]
    B --> C{Event open and seat available?}
    C -- No --> D[Return 404 or 409]
    C -- Yes --> E[Create active reservation with expires_at]
    E --> F[Commit hold]

    F --> G{Later reservation action}
    G -- Retrieve --> H[Lock seat then reservation; compare expiry to UTC now]
    H --> I{Expired?}
    I -- Yes --> J[Persist expired; seat becomes reusable]
    I -- No --> K[Return current reservation state]
    G -- Cancel --> L[Lock seat then reservation]
    L --> M{Still active and unexpired?}
    M -- Yes --> N[Persist cancelled; seat becomes reusable]
    M -- No --> O[Return conflict or preserve terminal state]

    F --> P[Client posts simulated checkout outcome]
    P --> Q[Locate reservation, then begin transaction]
    Q --> R[Lock seat row, then reservation row]
    R --> S{Existing checkout record?}
    S -- Yes --> T[Return original booking and payment; no new attempt]
    S -- No --> U{Active and unexpired?}
    U -- No, expired --> V[Persist expired and return 409]
    U -- No, cancelled or converted --> W[Return 409]
    U -- Yes --> X[Read authoritative ticket price from event]
    X --> Y{Simulated outcome}
    Y -- Success --> Z[Create confirmed booking and succeeded payment]
    Z --> ZA[Reservation becomes converted]
    Y -- Failure --> ZB[Create cancelled historical booking and failed payment]
    ZB --> ZC[Reservation becomes cancelled; seat is reusable]
    ZA --> ZD[Commit all checkout writes together]
    ZC --> ZD

    J --> AA[New reservation may reuse seat]
    N --> AA
    ZC --> AA
```

Every mutating reservation/checkout path locks the concrete seat before the
reservation row and uses a database transaction. A database error rolls back
the booking, payment, and reservation transition together. Expiry is lazy: no
background job currently expires untouched holds.
