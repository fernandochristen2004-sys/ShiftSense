"""ShiftSense web API."""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ShiftSense API", version="0.1.0")


class HealthResponse(BaseModel):
    """Response from the health check."""

    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API is running."""
    return HealthResponse(status="ok")