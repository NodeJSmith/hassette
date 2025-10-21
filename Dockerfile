# syntax=docker/dockerfile:1

# ---- Builder stage ----
FROM python:3.12-alpine AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/

# uncomment this if/when we need to build packages with native extensions
# RUN apk add --no-cache build-base

WORKDIR /app

# Copy lock + manifest for dependency resolution
ADD . /app

ENV UV_LINK_MODE=copy

# Set timezone to UTC as a default, user can override at runtime
ENV TZ=UTC

# Install deps (without project)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-editable --active

# Install project into venv (not editable, root owns at this point)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --active

# ---- Final stage ----
FROM python:3.12-alpine

# System packages you want available at runtime
RUN apk add --no-cache curl tini

WORKDIR /app

ENV UV_CACHE_DIR=/uv_cache

# Create non-root user first
RUN addgroup -S hassette \
    && adduser -S -G hassette -h /home/hassette hassette \
    && chown -R hassette:hassette /home/hassette \
    && mkdir -p $UV_CACHE_DIR \
    && chown -R hassette:hassette $UV_CACHE_DIR \
    && mkdir -p /config /data /apps \
    && chown -R hassette:hassette /config /data /apps /app

# Copy uv binary
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/

# Copy app, venv, scripts
COPY --from=builder --chown=hassette:hassette /app /app

USER hassette

# add OSTYPE to fix issue in python3.12 (https://github.com/python/cpython/issues/112252)
ENV HOME=/home/hassette \
    HASSETTE__CONFIG_DIR=/config \
    HASSETTE__DATA_DIR=/data \
    HASSETTE__APP_DIR=/apps \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/uv_cache \
    OSTYPE=linux \
    PATH="/app/.venv/bin:$PATH"

VOLUME ["/config", "/data", "/apps", "/uv_cache"]

ENTRYPOINT ["tini", "--", "/app/scripts/docker_start.sh"]
