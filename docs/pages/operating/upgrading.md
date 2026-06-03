# Upgrading Hassette

## Check Your Current Version

Before upgrading, confirm what version you're running. The CLI reports it directly:

```bash
hassette --version
```

To check the version installed in your project:

```bash
uv pip show hassette
```

## Upgrade

How you upgrade depends on how you installed Hassette.

**pip / uv (project install)**

```bash
uv add hassette@latest
```

This updates `pyproject.toml` and installs the new version into your project environment.

**Docker**

Pull the new image tag and restart your container:

```bash
docker pull ghcr.io/nodejsmith/hassette:latest
docker compose up -d
```

Replace `latest` with a specific version tag if you pin releases.

## Reading the Changelog

The changelog lives in two places: `CHANGELOG.md` at the root of the repository, and the [GitHub Releases page](https://github.com/NodeJSmith/hassette/releases). Both contain the same content. GitHub Releases is easier to browse by version; `CHANGELOG.md` is useful if you have the repo checked out.

Before upgrading, scan the entries between your current version and the target version. Pay attention to two signals:

- A `BREAKING CHANGE:` footer in a release note means something in your app code may need to change. The footer describes what changed and what you need to do.
- A `!` after the commit type (for example, `feat!:` or `fix!:`) marks a breaking change. If the entry has a `BREAKING CHANGE:` footer, that footer has the details. If it does not, the summary line is all you have. Read it carefully.

Entries without either signal are safe to take without changes to your app code.

## Major Version Upgrades

Hassette includes the major version in its data directory path. The current data directory is `~/.local/share/hassette/v0/`. A future v1 release will use `~/.local/share/hassette/v1/` and start with an empty database.

If you want to carry your history forward across a major version bump, set `data_dir` and `config_dir` explicitly in your `hassette.toml` before upgrading:

```toml
[hassette]
data_dir = "/home/youruser/.local/share/hassette/v0"
config_dir = "/home/youruser/.config/hassette/v0"
```

With explicit paths set, Hassette uses them regardless of the built-in version default. You control when the data moves.

Docker installations are unaffected. Mount points are version-independent. Your volume mounts stay the same across major versions.
