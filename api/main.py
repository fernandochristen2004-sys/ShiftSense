"""ShiftSense web API."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from api.convert import to_engine_inputs, to_schedule_response
from api.schemas import GenerateRequest, ScheduleResponse
from optimizer import engine

app = FastAPI(title="ShiftSense API", version="0.1.0")


class HealthResponse(BaseModel):
    """Response from the health check."""

    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API is running."""
    return HealthResponse(status="ok")


@app.post("/schedules/generate", response_model=ScheduleResponse)
def generate_schedule(request: GenerateRequest) -> ScheduleResponse:
    """Generate and validate a weekly schedule.

    Returns 422 if the input breaks a rule (for example, a shift that ends
    before it starts). An impossible schedule is not an error: it returns
    200 with status INFEASIBLE and no assignments.
    """
    try:
        result = engine.generate(**to_engine_inputs(request))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return to_schedule_response(result)
