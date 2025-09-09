# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /app

# Copy lock + manifest for dependency resolution first
COPY pyproject.toml uv.lock* ./

# Install deps (without project)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-editable

# Copy project source
COPY . .

# Install project into venv (not editable)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# ---- Final image ----
FROM python:3.12-slim

# Install curl for healthcheck (and clean up to keep it small)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root user first
RUN useradd -ms /bin/bash hassette

# Copy virtualenv
COPY --from=builder --chown=hassette:hassette /app/.venv /app/.venv

USER hassette

VOLUME ["/config", "/data", "/apps"]

ENV HASSETTE_CONFIG_DIR=/config \
    HASSETTE_DATA_DIR=/data \
    HASSETTE_APP_DIR=/apps \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Run via installed console script
ENTRYPOINT ["run-hassette"]
