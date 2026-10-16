"""FastAPI application and health endpoints."""

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from codechef_task.database import get_db_session
from codechef_task.checkout_routes import router as checkout_router
from codechef_task.reservation_routes import router as reservation_router

app = FastAPI(title="The Last Seat", version="0.1.0")
app.include_router(reservation_router)
app.include_router(checkout_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report that the API process is responding."""
    return {"status": "healthy"}


@app.get("/health/db")
async def database_health(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Check database connectivity without revealing connection details."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "database": "unavailable"},
        ) from None
    return {"status": "healthy", "database": "available"}
