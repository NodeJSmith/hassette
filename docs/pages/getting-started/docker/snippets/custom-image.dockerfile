FROM ghcr.io/nodejsmith/hassette:latest-py3.13

# Copy your project files
COPY pyproject.toml uv.lock /project/

# Export resolved deps as a flat requirements list
RUN uv export \
        --no-hashes --frozen \
        --directory /project \
        --no-default-groups \
        --no-dev --no-editable --no-emit-project \
        --output-file /tmp/user-deps.txt

# Install through constraints
RUN uv pip install -r /tmp/user-deps.txt -c /app/constraints.txt

# Install the project package itself (no dep resolution)
RUN uv pip install --no-deps /project

RUN rm /tmp/user-deps.txt
