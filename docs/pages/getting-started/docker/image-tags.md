# Docker Image Tags

Hassette publishes Docker images for multiple Python versions. All tags explicitly include the Python version to avoid ambiguity.

## Tag Format

### Recommended: Pin Both Version and Python

For reproducible production builds, pin both the Hassette version and Python version:

```
--8<-- "pages/getting-started/docker/snippets/tag-format-versioned.txt"
```

**Examples:**

- `ghcr.io/nodejsmith/hassette:0.24.0-py3.13`
- `ghcr.io/nodejsmith/hassette:0.24.0-py3.12`
- `ghcr.io/nodejsmith/hassette:0.24.0-py3.11`

This is the **preferred way** to consume Hassette in production.

### Track Latest Stable Release

If you want automatic upgrades within a Python line:

```
--8<-- "pages/getting-started/docker/snippets/tag-format-latest.txt"
```

**Examples:**

- `ghcr.io/nodejsmith/hassette:latest-py3.13`
- `ghcr.io/nodejsmith/hassette:latest-py3.12`
- `ghcr.io/nodejsmith/hassette:latest-py3.11`

!!! note "Stable Releases Only"
    These tags only point to stable releases. Pre-releases (`.dev`, `a`, `b`, `rc`, etc.) are never published to `latest-py*` tags.

!!! warning "Upgrade Risk"
    `latest-py*` tags update automatically on every stable release. If a new Hassette release includes breaking changes to configuration or app APIs, your container will silently upgrade on the next `docker pull`. Pin to a specific version if you need to control when upgrades happen.

### Testing Open Pull Requests

Pull requests opened from branches **in this repository** get a stable, mutable tag pointing at the latest build of that PR:

```
--8<-- "pages/getting-started/docker/snippets/tag-format-pr.txt"
```

**Example:**

- `ghcr.io/nodejsmith/hassette:pr-497-py3.13`

The tag is updated on every push to the PR branch, so `docker pull` always fetches the most recent build. Use these to try out changes before they land in `main`.

!!! note "Python 3.13 Only"
    PR images are only built for Python 3.13 to keep CI fast. Releases still build all supported Python versions.

!!! note "Fork PRs Not Published"
    PRs opened from forks do **not** publish images — fork-PR workflows do not have the credentials or write permissions needed to push to this repository's GHCR package. To test a fork PR, pull the contributor's branch locally and build the image yourself, or ask a maintainer to rebase the PR into the main repository.

!!! warning "Mutable Tag"
    `pr-<N>-py3.13` tags are mutable and will change as the PR evolves. Do not use them for reproducible builds — pin a version tag instead.

### Bleeding-Edge Main Branch

Every merge to `main` publishes a `main` tag for testing the latest unreleased code:

```
--8<-- "pages/getting-started/docker/snippets/tag-format-main.txt"
```

**Example:**

- `ghcr.io/nodejsmith/hassette:main-py3.13`

!!! note "Python 3.13 Only"
    `main` images are only built for Python 3.13 to keep CI fast. Releases still build all supported Python versions.

!!! warning "Mutable Tag"
    `main-py3.13` is mutable and updates on every merge to `main`. It may contain unreleased, unvetted changes. Do not use in production — pin a version tag instead.

## Tags NOT Published

The following tag patterns are **not** published:

| Pattern                            | Reason                                     |
| ---------------------------------- | ------------------------------------------ |
| `latest` (without Python version)  | Ambiguous — always specify Python version  |
| Version tags without `-py<python>` | Ambiguous — always specify Python version  |
| Floating tags for pre-releases     | Explicit version required for pre-releases |

If you want a pre-release, you must explicitly request it by version:

```
--8<-- "pages/getting-started/docker/snippets/tag-prerelease-explicit.txt"
```

## Supported Python Versions

Each release is built for multiple Python versions:

| Python Version | Status      |
| -------------- | ----------- |
| 3.13           | Supported |
| 3.12           | Supported |
| 3.11           | Supported |

!!! note "Version Support"
    Not all Python versions may be supported indefinitely. See release notes for changes to supported versions.

## Choosing a Tag

### For Production

Use a pinned version with your preferred Python:

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-pinned-compose.yml"
```

### For Development

Use the latest stable release:

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-latest-compose.yml"
```

### For Testing Pre-release Features

Use a specific pre-release version:

```yaml
--8<-- "pages/getting-started/docker/snippets/tag-prerelease-compose.yml"
```

## Updating Images

### Pull Latest

```bash
--8<-- "pages/getting-started/docker/snippets/docker-pull-update.sh"
```

### Check Current Version

```bash
--8<-- "pages/getting-started/docker/snippets/docker-version-check.sh"
```
