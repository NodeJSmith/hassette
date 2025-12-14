# Docker Image Tags

Hassette publishes Docker images for multiple Python versions. All tags explicitly include the Python version to avoid ambiguity.

## Tag Format

### Recommended: Pin Both Version and Python

For reproducible production builds, pin both the Hassette version and Python version:

```
ghcr.io/nodejsmith/hassette:<version>-py<python>
```

**Examples:**

- `ghcr.io/nodejsmith/hassette:1.2.0-py3.13`
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

### Development / CI Usage

For debugging or CI pinning to a specific commit:

```
ghcr.io/nodejsmith/hassette:sha-<commit>-py<python>
```

**Example:**

- `ghcr.io/nodejsmith/hassette:sha-a1b2c3d-py3.13`

These tags are immutable but intended for internal/testing use.

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
    image: ghcr.io/nodejsmith/hassette:1.2.0-py3.13
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
    image: ghcr.io/nodejsmith/hassette:1.3.0.dev1-py3.13
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

## See Also

- [Docker Overview](index.md) - Quick start guide
- [Building Your Own Image](index.md#building-your-own-image) - Custom image builds
