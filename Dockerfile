# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.9.8

# ---- uv stage ----
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---- Builder stage ----
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /bin/uv

WORKDIR /app

# Copy lock + manifest for dependency resolution
ADD . /app

ENV UV_LINK_MODE=copy

# Install deps (without project)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-editable --active --no-default-groups

# Install project into venv (not editable, root owns at this point)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --active --no-default-groups

# ---- Final stage ----
FROM python:${PYTHON_VERSION}-slim

# System packages you want available at runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tini \
    tzdata \
    fd-find \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_CACHE_DIR=/uv_cache
ENV TZ=UTC

# Create non-root user and needed directories
RUN groupadd --gid 1000 hassette \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/hassette hassette \
    && mkdir -p "$UV_CACHE_DIR" /config /data /apps \
    && chown -R 1000:1000 /home/hassette "$UV_CACHE_DIR" /config /data /apps /app

COPY --from=uv /uv /bin/uv
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
