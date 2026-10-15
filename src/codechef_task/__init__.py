"""The Last Seat application package."""

import uvicorn


def main() -> None:
    """Run the development API server."""
    uvicorn.run("codechef_task.app:app", host="127.0.0.1", port=8000)
