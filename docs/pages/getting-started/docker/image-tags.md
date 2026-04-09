# Docker Image Tags

Hassette publishes Docker images for multiple Python versions. All tags explicitly include the Python version to avoid ambiguity.

## Tag Format

### Recommended: Pin Both Version and Python

For reproducible production builds, pin both the Hassette version and Python version:

```
ghcr.io/nodejsmith/hassette:<version>-py<python>
```

**Examples:**

- `ghcr.io/nodejsmith/hassette:0.19.0-py3.13`
- `ghcr.io/nodejsmith/hassette:0.18.0-py3.12`
- `ghcr.io/nodejsmith/hassette:0.18.0.dev1-py3.11`

This is the **preferred way** to consume Hassette in production.

### Track Latest Stable Release

If you want automatic upgrades within a Python line:

```
ghcr.io/nodejsmith/hassette:latest-py<python>
```

**Examples:**

- `ghcr.io/nodejsmith/hassette:latest-py3.13`
- `ghcr.io/nodejsmith/hassette:latest-py3.12`
- `ghcr.io/nodejsmith/hassette:latest-py3.11`

!!! note "Stable Releases Only"
    These tags only point to stable releases. Pre-releases (`.dev`, `a`, `b`, `rc`, etc.) are never published to `latest-py*` tags.

### Testing Open Pull Requests

Every open pull request has a stable, mutable tag that points at the latest build of that PR:

```
ghcr.io/nodejsmith/hassette:pr-<number>-py3.13
```

**Example:**

- `ghcr.io/nodejsmith/hassette:pr-497-py3.13`

The tag is updated on every push to the PR branch, so `docker pull` always fetches the most recent build. Use these to try out changes before they land in `main`.

!!! note "Python 3.13 Only"
    PR images are only built for Python 3.13 to keep CI fast. Releases still build all supported Python versions.

!!! warning "Mutable Tag"
    `pr-<N>-py3.13` tags are mutable and will change as the PR evolves. Do not use them for reproducible builds — pin a version tag instead.

### Bleeding-Edge Main Branch

Every merge to `main` publishes a `main` tag for testing the latest unreleased code:

```
ghcr.io/nodejsmith/hassette:main-py3.13
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
| `latest` (without Python version)  | Ambiguous - always specify Python version  |
| Version tags without `-py<python>` | Ambiguous - always specify Python version  |
| Floating tags for pre-releases     | Explicit version required for pre-releases |

If you want a pre-release, you must explicitly request it by version:

```
ghcr.io/nodejsmith/hassette:0.18.0.dev1-py3.13
```

## Supported Python Versions

Each release is built for multiple Python versions:

| Python Version | Status      |
| -------------- | ----------- |
| 3.13           | ✅ Supported |
| 3.12           | ✅ Supported |
| 3.11           | ✅ Supported |

!!! note "Version Support"
    Not all Python versions may be supported indefinitely. See release notes for changes to supported versions.

## Choosing a Tag

### For Production

Use a pinned version with your preferred Python:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:0.19.0-py3.13
```

### For Development

Use the latest stable release:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest-py3.13
```

### For Testing New Features

Use a specific pre-release version:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:0.19.0.dev1-py3.13
```

## Updating Images

### Pull Latest

```bash
docker compose pull
docker compose up -d
```

### Check Current Version

```bash
docker compose exec hassette hassette --version
```
