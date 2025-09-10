#!/usr/bin/env sh

set -eu  # no pipefail in busybox ash

## We use a virtual environment because uv REALLY doesn't like to not use one
## plus it isolates the hassette dependencies from the host system
## so the first step is activate it

## then we look to see if there is a project to install in /apps
## if there is, we install it

## otherwise we look for hassette-requirements.txt/requirements.txt files in /config and /apps and install those

# ---- Activate venv (guard bash-isms in activate) -------------------------
# shellcheck disable=SC1091
. /app/.venv/bin/activate


APPS=/apps

# Check recursively under $CONF directory for additional python dependencies defined by the end-user via requirements.txt
# find $CONF -name requirements.txt -type f -not -empty -exec uv pip install -r {} --directory $APPS \;
# if pyproject.toml or uv.lock exists in $APPS, install that
if [ -f $APPS/pyproject.toml ] || [ -f $APPS/uv.lock ]; then
    uv sync --directory $APPS --no-default-groups --inexact --no-build-isolation --active # leave existing packages alone
fi

# find $CONF -name requirements.txt -type f -not -empty -exec uv pip install -r {} --directory $APPS \;
if uv run scripts/compile_requirements.py; then
    uv pip install -r /tmp/merged_requirements.txt --no-deps --no-build-isolation
fi

exec run-hassette
