# Image Tags

Hassette ships as a Docker image hosted at `ghcr.io/nodejsmith/hassette` (GitHub Container Registry). Each tag combines a Hassette version and a Python version — for example, `v0.39.0-py3.13`. That version is an example, not the current release.

The tag goes on the `image:` line of your `docker-compose.yml` from [Docker Setup](index.md).

## Which Tag to Use

For production, use a tag with a specific version number. Pick the newest `vX.Y.Z-py3.NN` tag from the [package's tag list](https://github.com/NodeJSmith/hassette/pkgs/container/hassette).

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-pinned-compose.yml"
```

A version-specific tag never changes — Docker downloads the same code every time.

For development, use `latest-py3.13`:

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-latest-compose.yml"
```

`latest-py3.*` tags track the most recent stable release. New features arrive on the next pull.

Python 3.11, 3.12, 3.13, and 3.14 are all supported. Replace `py3.13` in the tag with your preferred version.

## Updating

If you pinned a version, first change the version in the `image:` line to the new release. Then run this in the directory containing your `docker-compose.yml`:

```sh
--8<-- "pages/getting-started/docker/snippets/docker-pull-update.sh"
```

`pull` fetches the new image. `up -d` restarts the container with it. Docker prints the download progress, then a `Started` line — check the logs afterward to confirm Hassette reconnected.

The command alone only picks up new releases for `latest-py3.*` tags. A pinned tag pulls the same image again until you edit it.
