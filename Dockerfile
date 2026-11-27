# The ShiftSense API: FastAPI, the OR-Tools solver and database migrations.
# The dashboard (web/) is deployed separately, on Vercel.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq: the PostgreSQL client library psycopg talks through.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY db ./db
COPY optimizer ./optimizer
COPY services ./services
COPY api ./api

# Don't run as root.
RUN useradd --create-home shiftsense
USER shiftsense

EXPOSE 8000

# Bring the database up to date, then serve. Hosts like Render set PORT.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
