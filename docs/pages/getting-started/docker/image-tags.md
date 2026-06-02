# Docker Image Tags

Every image tag combines the Hassette version and the Python version: `ghcr.io/nodejsmith/hassette:<version>-py<python>`. For example, `v0.35.0-py3.13` means Hassette 0.35.0 on Python 3.13.

## Recommended Tags

### Production

Pin the Hassette version and the Python version. Your container won't change until you update the tag.

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-pinned-compose.yml"
```

### Development

Track the latest stable release for a given Python version.

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-latest-compose.yml"
```

`latest-py3.13` always points to the most recent stable release. It never includes pre-releases. Pull and restart when you want the newest version.

!!! warning "Automatic upgrades"
    `latest-py*` tags update on every stable release. If a new release has breaking changes, your container will pick them up on the next `docker pull`. Pin to a specific version if you need to control when upgrades happen.

## Supported Python Versions

Each release is built for three Python versions.

| Python version | Status    |
| -------------- | --------- |
| 3.13           | Supported |
| 3.12           | Supported |
| 3.11           | Supported |

Python versions are dropped when they reach end-of-life. Check the release notes when upgrading Hassette to a new minor version.

## Updating Images

Pull the latest image and restart your containers.

```bash
--8<-- "pages/getting-started/docker/snippets/docker-pull-update.sh"
```

If you pin to a specific version tag, update the tag in your `docker-compose.yml` first, then run this command.

## Next Steps

- [Docker Setup](index.md) — full setup guide
- [Dependencies](dependencies.md) — adding Python packages to your container
