#!/bin/sh

# shellcheck disable=SC1091
. /app/.venv/bin/activate

CONF=/config
APPS=/apps

# Check recursively under $CONF directory for additional python dependencies defined by the end-user via requirements.txt
# find $CONF -name requirements.txt -type f -not -empty -exec uv pip install -r {} --directory $APPS \;
# if pyproject.toml or uv.lock exists in $APPS, install that
if [ -f $APPS/pyproject.toml ] || [ -f $APPS/uv.lock ]; then

    uv sync --directory $APPS --no-default-groups --inexact --no-build-isolation --active # leave existing packages alone

    uv pip freeze
fi

find $CONF -name requirements.txt -type f -not -empty -exec uv pip install -r {} --directory $APPS \;

exec run-hassette
