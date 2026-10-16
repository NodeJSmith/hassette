# syntax=docker/dockerfile:1
# BASE_IMAGE has no default on purpose (below); skip the lint that flags that.
# check=skip=InvalidDefaultArgInFrom

# The Home Assistant add-on image: the published hassette image plus the add-on glue
# (design/specs/129-ha-addon-v01/design.md, D3). Build from the repo root:
#   docker build -f docker/addon/Dockerfile --build-arg BASE_IMAGE=<hassette image> --build-arg VERSION=<v> .
# Required: no default, so a build that forgets it fails instead of extending the wrong image.
ARG BASE_IMAGE
ARG TARGETARCH

# Supervisor names arm64 "aarch64"; one stage per platform adds its io.hass.arch label, and the final stage
# picks the one for the platform being built.
FROM ${BASE_IMAGE} AS base-amd64
LABEL io.hass.arch=amd64

FROM ${BASE_IMAGE} AS base-arm64
LABEL io.hass.arch=aarch64

FROM base-${TARGETARCH}

ARG VERSION
LABEL io.hass.type=app \
      io.hass.version=${VERSION}

# The base image runs as uid 1000, but Supervisor mounts the add-on's folders root-owned and run.sh writes
# to /config (D5).
USER root

COPY docker/addon/ /app/docker/addon/

# The start period must outlast the slowest start: every uv step timing out online and again offline, then
# hassette's own startup. tests/unit/test_addon_image.py fails when the uv timeouts outgrow it. 8126 is the
# port run.sh pins. A passing check
# ends the start period early, so a long one only delays noticing a start that never finishes (D14).
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=30m \
    CMD curl -fsS http://127.0.0.1:8126/api/health/live || exit 1

ENTRYPOINT ["tini", "--", "/app/docker/addon/run.sh"]
