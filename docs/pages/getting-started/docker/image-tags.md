# Image Tags

Images are published to `ghcr.io/nodejsmith/hassette`. Each tag combines a version and a Python version: `v{version}-py{python_version}`.

## Which Tag to Use

For production, pin to a specific version:

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-pinned-compose.yml"
```

A pinned tag never changes. You get the same code on every `pull`.

For development, use `latest-py3.13`:

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-latest-compose.yml"
```

`latest-py3.13` tracks the most recent stable release. New features arrive on the next pull.

Python 3.11, 3.12, 3.13, and 3.14 are all supported. Replace `py3.13` with your preferred version.

## Updating

```sh
--8<-- "pages/getting-started/docker/snippets/docker-pull-update.sh"
```

`pull` fetches the new image. `up -d` restarts the container with it.
