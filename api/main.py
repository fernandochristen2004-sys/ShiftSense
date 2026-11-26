"""ShiftSense web API."""

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.convert import (
    to_engine_inputs,
    to_repair_inputs,
    to_repair_response,
    to_schedule_response,
)
from api.schemas import (
    GenerateRequest,
    RepairRequest,
    RepairResponse,
    ScheduleResponse,
)
from api.restaurants import router as restaurants_router
from optimizer import engine

app = FastAPI(title="ShiftSense API", version="0.1.0")

# Browsers block a page on one address (the dashboard, port 3000) from calling
# an API on another (port 8000) unless the API allows it. Set
# SHIFTSENSE_CORS_ORIGINS to a comma-separated list to allow other addresses.
CORS_ORIGINS = os.environ.get(
    "SHIFTSENSE_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in CORS_ORIGINS if origin.strip()],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(restaurants_router)


class HealthResponse(BaseModel):
    """Response from the health check."""

    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API is running."""
    return HealthResponse(status="ok")


# Stateless endpoints: everything is sent in the request and nothing is saved.
# Useful for trying the engine. The stored-data workflow is in api/restaurants.py.

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


@app.post("/schedules/repair", response_model=RepairResponse)
def repair_schedule(request: RepairRequest) -> RepairResponse:
    """Repair a published schedule after one or more call-outs.

    Coverage comes first, then the fewest changes, then fairness. The
    response lists every change. If a call-out can't be covered without
    breaking a hard minimum, the status is INFEASIBLE (200, no assignments).
    """
    try:
        inputs = to_repair_inputs(request)
        result = engine.repair(**inputs)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return to_repair_response(result, inputs["original_schedule"])
