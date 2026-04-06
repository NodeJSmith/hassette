# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.9.8

# ---- Frontend stage (Node.js — builds the Preact SPA) ----
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- uv stage ----
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---- Builder stage ----
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /bin/uv

WORKDIR /app

# Copy lock + manifest for dependency resolution
ADD ./src /app/src
# Copy SPA build output from frontend stage (vite outputs to ../src/hassette/web/static/spa relative to WORKDIR)
COPY --from=frontend /app/src/hassette/web/static/spa/ /app/src/hassette/web/static/spa/
ADD ./scripts /app/scripts
ADD ./tools /app/tools
ADD ./pyproject.toml /app/pyproject.toml
ADD ./uv.lock /app/uv.lock
ADD ./README.md /app/README.md

# add .ignore file, fdfind will use this - helpful when troubleshooting
ADD ./scripts/.ignore /app/.ignore

ENV UV_LINK_MODE=copy

# Fail the build if uv.lock is stale relative to pyproject.toml
RUN uv lock --check

# Install deps (without project)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-editable --active --no-default-groups

# Install project into venv (not editable, root owns at this point)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --active --no-default-groups

# Generate constraints file from declared dependency ranges (not lockfile pins).
# Must use the venv Python so importlib.metadata can find the installed hassette version.
RUN /app/.venv/bin/python tools/generate_constraints.py > /app/constraints.txt \
 && /app/.venv/bin/python -c "\
import tomllib; \
lines=[l for l in open('/app/constraints.txt').read().splitlines() if l and not l.startswith('#')]; \
deps=tomllib.load(open('/app/pyproject.toml','rb')).get('project',{}).get('dependencies',[]); \
expected=len(deps)+1; \
assert len(lines)==expected, f'constraints.txt has {len(lines)} entries, expected {expected}'; \
assert lines[-1].startswith('hassette=='), f'last line should be hassette pin, got {lines[-1]!r}'"

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
